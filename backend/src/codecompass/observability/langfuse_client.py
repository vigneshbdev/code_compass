"""Langfuse access that fails open (research R10, task T023).

If Langfuse is disabled or unreachable, chat keeps working: callers get a run config with a
no-op handler, and score/delete helpers log and swallow errors. Langfuse is the system of
record for traces.

With the Langfuse v5 SDK, trace name, session and user are passed as LangChain run metadata
(`langfuse_trace_name`, `langfuse_session_id`, `langfuse_user_id`), so `run_config()` returns a
ready-to-use LangChain `RunnableConfig` rather than a bare handler.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig

from codecompass.config import Settings
from codecompass.guardrails.redaction import SecretDetector

logger = logging.getLogger(__name__)

LangfuseState = Literal["ok", "unreachable", "disabled"]
HEALTH_PATH = "/api/public/health"
USER_ID = "local"  # single user, no auth (spec Assumptions)


_DETECTOR = SecretDetector()


def mask_secrets(*, data: Any, **_: Any) -> Any:
    """Langfuse export mask (FR-033, SC-004): redact secrets in every traced payload.

    LangChain callbacks record the model's raw output before the streaming output rail, so the
    export boundary needs its own guard.
    """
    if isinstance(data, str):
        return _DETECTOR.redact(data)[0]
    if isinstance(data, dict):
        return {k: mask_secrets(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask_secrets(data=v) for v in data]
    return data


class NoopHandler(BaseCallbackHandler):
    """Stands in for the Langfuse handler when tracing is off or broken."""


class TraceHandle:
    """A manually started trace (used where LangChain callbacks don't reach, e.g. ingestion)."""

    def __init__(self, span: Any | None = None) -> None:
        self._span = span
        self.trace_id: str | None = getattr(span, "trace_id", None) if span is not None else None

    def end(self, *, output: Any = None, level: str | None = None) -> None:
        if self._span is None:
            return
        try:
            self._span.update(output=output, level=level)
            self._span.end()
        except Exception:
            logger.exception("Langfuse span end failed")


class RequestTrace:
    """One chat request's trace: LangChain runs inside it nest as child observations."""

    def __init__(
        self, trace_id: str | None, handler: BaseCallbackHandler, span: Any | None = None
    ) -> None:
        self.trace_id = trace_id
        self.handler = handler
        self._span = span

    def config(self, run_name: str) -> RunnableConfig:
        return RunnableConfig(callbacks=[self.handler], run_name=run_name)

    def update(self, *, output: Any = None, metadata: dict[str, Any] | None = None) -> None:
        if self._span is None:
            return
        try:
            self._span.update(output=output, metadata=metadata)
        except Exception:
            logger.exception("Langfuse trace update failed")


class LangfuseClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport  # tests inject a mock transport for check()
        self._client: Any | None = None
        self._handler_failed_logged = False
        if settings.langfuse_enabled:
            self._client = self._try_create_client()

    @property
    def client(self) -> Any | None:
        return self._client

    def _try_create_client(self) -> Any | None:
        s = self._settings
        if not (s.langfuse_public_key and s.langfuse_secret_key):
            logger.warning("Langfuse enabled but keys are missing; tracing is off")
            return None
        try:
            from langfuse import Langfuse

            return Langfuse(
                public_key=s.langfuse_public_key,
                secret_key=s.langfuse_secret_key.get_secret_value(),
                host=s.langfuse_host,
                mask=mask_secrets,
            )
        except Exception:
            logger.exception("Langfuse client init failed; tracing is off")
            return None

    def _handler(self) -> BaseCallbackHandler:
        if self._client is None:
            return NoopHandler()
        try:
            from langfuse.langchain import CallbackHandler

            handler: BaseCallbackHandler = CallbackHandler(
                public_key=self._settings.langfuse_public_key
            )
            return handler
        except Exception:
            if not self._handler_failed_logged:
                logger.exception("Langfuse callback handler unavailable; tracing is off")
                self._handler_failed_logged = True
            return NoopHandler()

    def run_config(
        self,
        trace_name: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunnableConfig:
        """LangChain run config that traces one request (or does nothing when tracing is off)."""
        # Caller metadata first, so it can never overwrite the Langfuse trace keys.
        run_metadata: dict[str, Any] = {
            **(metadata or {}),
            "langfuse_trace_name": trace_name,
            "langfuse_user_id": USER_ID,
        }
        if session_id:
            run_metadata["langfuse_session_id"] = session_id
        return RunnableConfig(
            callbacks=[self._handler()], run_name=trace_name, metadata=run_metadata
        )

    @contextmanager
    def request_trace(
        self, name: str, session_id: str | None = None, metadata: dict[str, Any] | None = None
    ) -> Iterator[RequestTrace]:
        """Open a trace for one request; yields a no-op trace when tracing is unavailable."""
        if self._client is None:
            yield RequestTrace(None, NoopHandler())
            return
        try:
            from langfuse import propagate_attributes

            span_cm = self._client.start_as_current_observation(
                name=name, as_type="chain", metadata=metadata
            )
            attrs_cm = propagate_attributes(session_id=session_id, user_id=USER_ID, trace_name=name)
        except Exception:
            logger.exception("Langfuse request trace unavailable")
            yield RequestTrace(None, NoopHandler())
            return
        with span_cm as span, attrs_cm:
            yield RequestTrace(getattr(span, "trace_id", None), self._handler(), span)

    def trace_url(self, trace_id: str | None) -> str | None:
        if not trace_id or not self._settings.langfuse_enabled:
            return None
        base = self._settings.langfuse_ui_url.rstrip("/")
        project = self._settings.langfuse_project_id
        return (
            f"{base}/project/{project}/traces/{trace_id}" if project else f"{base}/trace/{trace_id}"
        )

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> TraceHandle:
        """Start a manual trace; returns a no-op handle when tracing is off or broken."""
        if self._client is None:
            return TraceHandle()
        try:
            span = self._client.start_observation(name=name, as_type="span", metadata=metadata)
            return TraceHandle(span)
        except Exception:
            logger.exception("Langfuse start_trace failed")
            return TraceHandle()

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None:
        if self._client is None:
            return
        try:
            self._client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
        except Exception:
            logger.exception(
                "Langfuse score failed", extra={"data": {"trace_id": trace_id, "name": name}}
            )

    def delete_traces(self, trace_ids: list[str]) -> None:
        if self._client is None or not trace_ids:
            return
        try:
            self._client.api.trace.delete_multiple(trace_ids=trace_ids)
        except Exception:
            logger.exception(
                "Langfuse trace delete failed", extra={"data": {"count": len(trace_ids)}}
            )

    async def check(self) -> LangfuseState:
        if not self._settings.langfuse_enabled:
            return "disabled"
        if self._client is None:
            return "unreachable"
        try:
            async with httpx.AsyncClient(timeout=3, transport=self._transport) as http:
                response = await http.get(self._settings.langfuse_host.rstrip("/") + HEALTH_PATH)
        except httpx.HTTPError:
            return "unreachable"
        return "ok" if response.status_code == 200 else "unreachable"

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:
            logger.exception("Langfuse flush failed")
