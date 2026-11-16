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
    return Settings(_env_file=None, langfuse_enabled=False)


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


class FakeSpan:
    trace_id = "trace-123"

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.ended = False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class SpanClient:
    def __init__(self, span: FakeSpan | None = None, fail: bool = False) -> None:
        self.span, self.fail = span, fail

    def start_observation(self, **_: Any) -> FakeSpan:
        if self.fail or self.span is None:
            raise ConnectionError("down")
        return self.span


def test_start_trace_disabled_is_noop(base_settings: Settings) -> None:
    handle = LangfuseClient(base_settings).start_trace("ingestion")
    assert handle.trace_id is None
    handle.end(output={"x": 1})  # must not raise


def test_start_trace_records_and_ends_span(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings)
    span = FakeSpan()
    lf._client = SpanClient(span)
    handle = lf.start_trace("ingestion", {"codebase_id": "c1"})
    assert handle.trace_id == "trace-123"
    handle.end(output={"indexed": 3})
    assert span.ended and span.updates == [{"output": {"indexed": 3}, "level": None}]


def test_start_trace_fails_open(base_settings: Settings) -> None:
    lf = LangfuseClient(base_settings)
    lf._client = SpanClient(fail=True)
    handle = lf.start_trace("ingestion")
    assert handle.trace_id is None
    handle.end()


def test_sc004_export_mask_redacts_nested_payloads() -> None:
    from codecompass.observability.langfuse_client import mask_secrets
    from tests.fixtures import repos

    secret = repos.SECRETS[0].value
    data = {"output": f"key {secret}", "messages": [{"content": f"x {secret}"}], "n": 3}
    masked = mask_secrets(data=data)
    assert secret not in repr(masked)
    assert masked["n"] == 3 and "[REDACTED:aws_access_key]" in masked["output"]


def test_sc004_real_client_is_created_with_the_mask(
    base_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langfuse

    from codecompass.observability.langfuse_client import mask_secrets

    seen: dict[str, Any] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    settings = base_settings.model_copy(
        update={
            "langfuse_enabled": True,
            "langfuse_public_key": "pk",
            "langfuse_secret_key": SecretStr("sk"),
        }
    )
    LangfuseClient(settings)
    assert seen["mask"] is mask_secrets
