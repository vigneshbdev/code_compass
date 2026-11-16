"""In-memory stand-in for Langfuse (task T021): records runs, prompts, documents and scores.

Used by trace tests (FR-040, FR-041, SC-004) to assert what *would* be sent to Langfuse.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from codecompass.config import Settings
from codecompass.observability.langfuse_client import (
    LangfuseClient,
    LangfuseState,
    RequestTrace,
    mask_secrets,
)


@dataclass
class RecordedEvent:
    kind: str  # chain_start | chain_end | chat_model_start | llm_end | retriever_end | error
    run_id: UUID
    parent_run_id: UUID | None
    name: str | None = None
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RecordingHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self.events: list[RecordedEvent] = []

    def _add(self, kind: str, run_id: UUID, parent_run_id: UUID | None, **kw: Any) -> None:
        self.events.append(RecordedEvent(kind, run_id, parent_run_id, **kw))

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        self._add(
            "chain_start",
            run_id,
            parent_run_id,
            name=kw.get("name"),
            payload=inputs,
            metadata=metadata or {},
        )

    def on_chain_end(
        self, outputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any
    ) -> None:
        self._add("chain_end", run_id, parent_run_id, payload=outputs)

    def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        self._add(
            "chat_model_start",
            run_id,
            parent_run_id,
            name=kw.get("name"),
            payload=messages,
            metadata=metadata or {},
        )

    def on_llm_end(
        self, response: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any
    ) -> None:
        self._add("llm_end", run_id, parent_run_id, payload=response)

    def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kw: Any,
    ) -> None:
        self._add("retriever_end", run_id, parent_run_id, payload=documents)

    def on_chain_error(
        self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any
    ) -> None:
        self._add("error", run_id, parent_run_id, payload=error)

    def all_text(self) -> str:
        """What Langfuse would receive, as one string, for SC-004 sweeps.

        The real client applies `mask_secrets` at export; so does this recorder.
        """
        raw = "\n".join(repr(e.payload) + repr(e.metadata) for e in self.events)
        masked: str = mask_secrets(data=raw)
        return masked


class CaptureTracer(LangfuseClient):
    """A LangfuseClient whose run configs record locally instead of exporting."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.model_copy(update={"langfuse_enabled": False}))
        self.handlers: list[RecordingHandler] = []
        self.configs: list[RunnableConfig] = []
        self.scores: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.traces: list[_RecordingTrace] = []

    def run_config(
        self,
        trace_name: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunnableConfig:
        config = super().run_config(trace_name, session_id, metadata)
        handler = RecordingHandler()
        self.handlers.append(handler)
        config["callbacks"] = [handler]
        self.configs.append(config)
        return config

    @contextmanager
    def request_trace(
        self, name: str, session_id: str | None = None, metadata: dict[str, Any] | None = None
    ) -> Iterator[RequestTrace]:
        handler = RecordingHandler()
        self.handlers.append(handler)
        trace = _RecordingTrace(uuid_module.uuid4().hex, handler, self, name, session_id, metadata)
        self.traces.append(trace)
        yield trace

    def trace_url(self, trace_id: str | None) -> str | None:
        return f"http://langfuse.test/trace/{trace_id}" if trace_id else None

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None:
        self.scores.append({"trace_id": trace_id, "name": name, "value": value, "comment": comment})

    def delete_traces(self, trace_ids: list[str]) -> None:
        self.deleted.extend(trace_ids)

    async def check(self) -> LangfuseState:
        return "ok"

    def all_text(self) -> str:
        parts = [h.all_text() for h in self.handlers]
        parts += [mask_secrets(data=repr(t.updates)) for t in self.traces]
        return "\n".join(parts) + repr(self.configs)


class _RecordingTrace(RequestTrace):
    def __init__(
        self,
        trace_id: str,
        handler: RecordingHandler,
        owner: CaptureTracer,
        name: str,
        session_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        super().__init__(trace_id, handler)
        self.name = name
        self.session_id = session_id
        self.metadata = metadata or {}
        self.updates: list[dict[str, Any]] = []

    def update(self, *, output: Any = None, metadata: dict[str, Any] | None = None) -> None:
        self.updates.append({"output": output, "metadata": metadata})
