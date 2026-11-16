"""The chat request, end to end (FR-010…FR-016, FR-031…FR-033, FR-040, C4; tasks T142-T146).

input rail (NeMo) → rewrite (fast model) → hybrid retrieval → pre-check → answer stream
(LangChain + LiteLLM) → output rail (NeMo, per line) → citation validation → persistence.

Everything runs inside one Langfuse trace (session = conversation), so each step appears as a
child span, and the trace gets the FR-040 metadata (retrieval table, guardrail decisions,
latency) plus citation scores.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessageChunk

from codecompass.api.errors import AppError, ErrorCode
from codecompass.chat.citations import NOT_FOUND, Citation, answer_status, validate
from codecompass.chat.context import format_chunks, format_history
from codecompass.chat.events import ChatEvent
from codecompass.chat.rewrite import rewrite_question
from codecompass.config import Settings
from codecompass.guardrails.rails import Guardrails, OutputFilter
from codecompass.llm.factory import ModelFactory, cost_usd
from codecompass.observability.langfuse_client import LangfuseClient, RequestTrace
from codecompass.observability.prompt_sync import PromptRegistry
from codecompass.retrieval.hybrid import HybridRetriever, RetrievalResult
from codecompass.storage.db import Database
from codecompass.storage.repositories import codebases as codebase_repo
from codecompass.storage.repositories import conversations as conversation_repo

logger = logging.getLogger(__name__)

DECLINED = (
    "I can only help with questions about this codebase or software engineering. "
    "Try asking where something is implemented or how part of the code works."
)


@dataclass
class ChatContext:
    conversation_id: uuid.UUID
    codebase_id: uuid.UUID
    ingestion_id: uuid.UUID


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _retrieval_table(result: RetrievalResult) -> list[dict[str, Any]]:
    keys = (
        "path",
        "start_line",
        "end_line",
        "symbol",
        "vector_rank",
        "vector_score",
        "lexical_rank",
        "lexical_score",
        "symbol_hit",
        "fused_score",
        "packed",
    )
    return [{k: d.metadata.get(k) for k in keys} for d in result.ranked]


class ChatService:
    def __init__(
        self,
        db: Database,
        models: ModelFactory,
        settings: Settings,
        langfuse: LangfuseClient,
        prompts: PromptRegistry,
        guardrails: Guardrails,
    ) -> None:
        self._db = db
        self._models = models
        self._settings = settings
        self._langfuse = langfuse
        self._prompts = prompts
        self._guardrails = guardrails
        self._retriever = HybridRetriever(db.sessions, models.embeddings(), settings)

    async def prepare(self, conversation_id: str) -> ChatContext:
        """Validate before streaming starts, so errors are normal JSON responses (409/404)."""
        async with self._db.sessions() as session:
            conversation = await conversation_repo.get(session, conversation_id)
            codebase = await codebase_repo.ensure_chat_ready(
                session, conversation.codebase_id, self._settings
            )
            assert codebase.active_ingestion_id is not None
            return ChatContext(conversation.id, codebase.id, codebase.active_ingestion_id)

    async def _history(self, conversation_id: uuid.UUID) -> list[tuple[str, str]]:
        async with self._db.sessions() as session:
            return [
                (m.role, m.content)
                for m in await conversation_repo.messages(session, conversation_id)
            ]

    async def stream(
        self,
        ctx: ChatContext,
        question: str,
        observer: Callable[[RetrievalResult], None] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Stream one answer. `observer` receives the retrieval result (used by `make eval`)."""
        started = time.perf_counter()
        history = await self._history(ctx.conversation_id)
        async with self._db.sessions() as session, session.begin():
            conversation = await conversation_repo.get(session, ctx.conversation_id)
            await conversation_repo.set_title_if_new(session, conversation, question)
            user_msg = await conversation_repo.add_message(
                session, ctx.conversation_id, role="user", content=question, status="complete"
            )
            user_message_id = user_msg.id
        assistant_message_id = uuid.uuid4()

        metadata = {
            "codebase_id": str(ctx.codebase_id),
            "conversation_id": str(ctx.conversation_id),
        }
        with self._langfuse.request_trace("chat", str(ctx.conversation_id), metadata) as trace:
            async for event in self._run(
                ctx,
                question,
                history,
                trace,
                started,
                user_message_id,
                assistant_message_id,
                observer,
            ):
                yield event

    async def _run(
        self,
        ctx: ChatContext,
        question: str,
        history: list[tuple[str, str]],
        trace: RequestTrace,
        started: float,
        user_message_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        observer: Callable[[RetrievalResult], None] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        latency: dict[str, int] = {}
        guardrails: dict[str, Any] = {
            "input": "allowed",
            "injection_flagged_chunks": [],
            "output_redactions": 0,
            "not_found_precheck": False,
        }
        rewritten: str | None = None
        result: RetrievalResult | None = None
        answer = ""
        status = "complete"
        citations: list[Citation] = []
        invalid = 0
        usage = {"tokens_in": 0, "tokens_out": 0}
        meta_sent = False
        try:
            # 1. Input rail (FR-032): question plus recent questions, so follow-ups pass.
            t = time.perf_counter()
            recent = [content for role, content in history if role == "user"]
            allowed = await self._guardrails.check_input(question, recent)
            latency["input_rails"] = _ms(t)
            if not allowed:
                guardrails["input"] = "declined"
                status, answer = "declined", DECLINED
            else:
                # 2. Rewrite follow-ups (FR-014) and collect identifiers (FR-015).
                t = time.perf_counter()
                rewrite = await rewrite_question(
                    self._models.chat("fast"),
                    self._prompts.get("rewrite").template,
                    question,
                    format_history(history) if history else "",
                    trace.config("rewrite"),
                )
                rewritten = rewrite.standalone_question
                latency["rewrite"] = _ms(t)

                # 3. Hybrid retrieval scoped to this codebase (FR-006).
                t = time.perf_counter()
                result = await self._retriever.retrieve(
                    rewritten, rewrite.identifiers, ctx.ingestion_id, trace.config("retrieve")
                )
                latency["retrieve"] = _ms(t)
                if observer is not None:
                    observer(result)
                guardrails["injection_flagged_chunks"] = [
                    d.metadata["chunk_id"]
                    for d in result.packed
                    if d.metadata.get("injection_flag")
                ]
                if not result.found:  # FR-013 pre-check: no LLM call
                    guardrails["not_found_precheck"] = True
                    status, answer = "not_found", NOT_FOUND

            yield ChatEvent(
                "meta",
                {
                    "user_message_id": str(user_message_id),
                    "assistant_message_id": str(assistant_message_id),
                    "trace_id": trace.trace_id,
                    "trace_url": self._langfuse.trace_url(trace.trace_id),
                    "rewritten_query": rewritten,
                },
            )
            meta_sent = True

            if answer:  # declined or not found: fixed text, no generation
                yield ChatEvent("token", {"text": answer})
            else:
                assert result is not None
                output = OutputFilter(self._guardrails)
                prompt = self._prompts.get("answer").template.format_messages(
                    history=format_history(history),
                    context=format_chunks(result.packed),
                    question=question,
                )
                t = time.perf_counter()
                model = self._models.chat("answer", streaming=True)
                async for chunk in model.astream(prompt, config=trace.config("answer")):
                    if isinstance(chunk, AIMessageChunk) and chunk.usage_metadata:
                        usage["tokens_in"] = chunk.usage_metadata.get("input_tokens", 0)
                        usage["tokens_out"] = chunk.usage_metadata.get("output_tokens", 0)
                    delta = chunk.content if isinstance(chunk.content, str) else ""
                    safe = await output.feed(delta)  # FR-033: output rail before the client
                    if safe:
                        latency.setdefault("first_token", _ms(started))
                        answer += safe
                        yield ChatEvent("token", {"text": safe})
                tail = await output.flush()
                if tail:
                    latency.setdefault("first_token", _ms(started))
                    answer += tail
                    yield ChatEvent("token", {"text": tail})
                latency["generate"] = _ms(t)
                guardrails["output_redactions"] = output.redactions
                citations, invalid = validate(answer, result.packed)
                status = answer_status(answer, citations)

            yield ChatEvent(
                "citations",
                {
                    "citations": [
                        {"path": c.path, "start_line": c.start_line, "end_line": c.end_line}
                        for c in citations
                    ]
                },
            )
            latency["total"] = _ms(started)
            cost = cost_usd(self._settings.llm_model, usage["tokens_in"], usage["tokens_out"])
            usage_out = {**usage, "cost_usd": cost, "latency_ms": latency}
            await self._save(ctx, assistant_message_id, answer, status, trace, usage_out, citations)
            self._finish_trace(
                trace,
                question,
                rewritten,
                answer,
                status,
                result,
                guardrails,
                latency,
                citations,
                invalid,
            )
            yield ChatEvent("done", {"status": status, "usage": usage_out, "latency_ms": latency})
        except AppError:
            raise
        except Exception:
            logger.exception("chat request failed")
            if not meta_sent:
                yield ChatEvent(
                    "meta",
                    {
                        "user_message_id": str(user_message_id),
                        "assistant_message_id": str(assistant_message_id),
                        "trace_id": trace.trace_id,
                        "trace_url": self._langfuse.trace_url(trace.trace_id),
                        "rewritten_query": rewritten,
                    },
                )
            await self._save(
                ctx,
                assistant_message_id,
                answer,
                "error",
                trace,
                {**usage, "latency_ms": latency},
                [],
            )
            yield ChatEvent(
                "error",
                {
                    "code": ErrorCode.LLM_UNAVAILABLE.value,
                    "message": "The model provider failed while answering. Try again in a moment.",
                    "partial": bool(answer),
                },
            )

    async def _save(
        self,
        ctx: ChatContext,
        message_id: uuid.UUID,
        content: str,
        status: str,
        trace: RequestTrace,
        usage: dict[str, Any],
        citations: list[Citation],
    ) -> None:
        async with self._db.sessions() as session, session.begin():
            await conversation_repo.add_message(
                session,
                ctx.conversation_id,
                id=message_id,
                role="assistant",
                content=content,
                status=status,
                trace_id=trace.trace_id,
                usage=usage,
            )
            await conversation_repo.add_citations(
                session,
                message_id,
                [
                    {
                        "path": c.path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "chunk_id": c.chunk_id,
                        "content_hash": c.content_hash,
                        "ordinal": c.ordinal,
                    }
                    for c in citations
                ],
            )

    def _finish_trace(
        self,
        trace: RequestTrace,
        question: str,
        rewritten: str | None,
        answer: str,
        status: str,
        result: RetrievalResult | None,
        guardrails: dict[str, Any],
        latency: dict[str, int],
        citations: list[Citation],
        invalid: int,
    ) -> None:
        """FR-040 fields LangChain spans don't carry, plus citation scores (SC-003)."""
        trace.update(
            output={"answer": answer, "status": status},
            metadata={
                "query": question,
                "rewritten_query": rewritten,
                "retrieval": _retrieval_table(result) if result else [],
                "guardrails": guardrails,
                "latency_ms": latency,
                "model": self._settings.llm_model,
                "prompt_versions": {
                    name: self._prompts.get(name).version for name in ("rewrite", "answer")
                },
            },
        )
        if trace.trace_id:
            self._langfuse.score(trace.trace_id, "citations_valid", len(citations))
            self._langfuse.score(trace.trace_id, "citations_invalid", invalid)
