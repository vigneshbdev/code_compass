"""In-memory stand-in for Langfuse (task T021): records runs, prompts, documents and scores.

Used by trace tests (FR-040, FR-041, SC-004) to assert what *would* be sent to Langfuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from codecompass.config import Settings
from codecompass.observability.langfuse_client import LangfuseClient, LangfuseState


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
        documents: list[Document],
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
        """Everything recorded, as one string, for "secret never appears" sweeps (SC-004)."""
        return "\n".join(repr(e.payload) + repr(e.metadata) for e in self.events)


class CaptureTracer(LangfuseClient):
    """A LangfuseClient whose run configs record locally instead of exporting."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.model_copy(update={"langfuse_enabled": False}))
        self.handlers: list[RecordingHandler] = []
        self.configs: list[RunnableConfig] = []
        self.scores: list[dict[str, Any]] = []
        self.deleted: list[str] = []

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

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None:
        self.scores.append({"trace_id": trace_id, "name": name, "value": value, "comment": comment})

    def delete_traces(self, trace_ids: list[str]) -> None:
        self.deleted.extend(trace_ids)

    async def check(self) -> LangfuseState:
        return "ok"

    def all_text(self) -> str:
        return "\n".join(h.all_text() for h in self.handlers) + repr(self.configs)
