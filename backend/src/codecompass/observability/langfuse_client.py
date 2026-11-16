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
from typing import Any, Literal

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig

from codecompass.config import Settings

logger = logging.getLogger(__name__)

LangfuseState = Literal["ok", "unreachable", "disabled"]
HEALTH_PATH = "/api/public/health"
USER_ID = "local"  # single user, no auth (spec Assumptions)


class NoopHandler(BaseCallbackHandler):
    """Stands in for the Langfuse handler when tracing is off or broken."""


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
