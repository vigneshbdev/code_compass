"""Langfuse client fails open (research R10, FR-040/FR-041 plumbing, task T023)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from codecompass.config import Settings
from codecompass.observability.langfuse_client import LangfuseClient, NoopHandler


@pytest.fixture
def base_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in {
        "DATABASE_URL": "postgresql+psycopg://u:p@db:5432/codecompass",
        "LLM_MODEL": "m",
        "LLM_FAST_MODEL": "m",
        "LLM_JUDGE_MODEL": "m",
        "EMBEDDING_MODEL": "m",
        "EMBEDDING_DIM": "8",
    }.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None, langfuse_enabled=False)  # type: ignore[call-arg]


class ExplodingClient:
    """Stands in for the Langfuse SDK client; every call fails."""

    def __init__(self) -> None:
        self.api = self

    def create_score(self, **_: Any) -> None:
        raise ConnectionError("down")

    @property
    def trace(self) -> ExplodingClient:
        return self

    def delete_multiple(self, **_: Any) -> None:
        raise ConnectionError("down")

    def flush(self) -> None:
        raise ConnectionError("down")


def test_disabled_gives_noop_run_config_with_trace_metadata(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings)
    config = lf.run_config("chat", session_id="conv-1", metadata={"codebase_id": "cb-1"})
    assert isinstance(config["callbacks"][0], NoopHandler)  # type: ignore[index]
    assert config["run_name"] == "chat"
    assert config["metadata"] == {
        "langfuse_trace_name": "chat",
        "langfuse_user_id": "local",
        "langfuse_session_id": "conv-1",
        "codebase_id": "cb-1",
    }


def test_enabled_without_keys_turns_tracing_off(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings.model_copy(update={"langfuse_enabled": True}))
    assert lf.client is None
    assert isinstance(lf.run_config("chat")["callbacks"][0], NoopHandler)  # type: ignore[index]


def test_helpers_swallow_langfuse_errors(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings)
    lf._client = ExplodingClient()
    lf.score("t1", "user_feedback", 1)  # must not raise (FR-041 still succeeds)
    lf.delete_traces(["t1"])  # must not raise (FR-007 delete still succeeds)
    lf.flush()


def test_helpers_are_noops_when_disabled(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings)
    lf.score("t1", "x", 1)
    lf.delete_traces(["t1"])
    lf.flush()


async def test_check_disabled(base_settings: Settings) -> None:
    assert await LangfuseClient(base_settings).check() == "disabled"


def _enabled(base_settings: Settings, transport: httpx.MockTransport) -> LangfuseClient:
    settings = base_settings.model_copy(
        update={
            "langfuse_enabled": True,
            "langfuse_public_key": "pk-lf-test",
            "langfuse_secret_key": SecretStr("sk-lf-test"),
            "langfuse_host": "http://langfuse.test",
        }
    )
    return LangfuseClient(settings, transport=transport)


@pytest.mark.parametrize(("status", "expected"), [(200, "ok"), (503, "unreachable")])
async def test_check_reflects_health_endpoint(
    base_settings: Settings, status: int, expected: str
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    assert await _enabled(base_settings, transport).check() == expected


async def test_check_connection_error_is_unreachable(base_settings: Settings) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert await _enabled(base_settings, httpx.MockTransport(refuse)).check() == "unreachable"


def test_caller_metadata_cannot_override_trace_keys(base_settings: Settings) -> None:
    config = LangfuseClient(base_settings).run_config(
        "chat", metadata={"langfuse_trace_name": "spoofed", "langfuse_user_id": "x"}
    )
    assert config["metadata"]["langfuse_trace_name"] == "chat"
    assert config["metadata"]["langfuse_user_id"] == "local"
