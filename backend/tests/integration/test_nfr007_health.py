"""NFR-007: key required, fail fast with a clear message, never crash (task T012)."""

from __future__ import annotations

import httpx
import pytest

from codecompass.config import Settings
from codecompass.llm.factory import CheckResult
from codecompass.observability.langfuse_client import LangfuseClient, LangfuseState
from tests.conftest import ClientFactory
from tests.fakes.capture_tracer import CaptureTracer
from tests.fakes.fake_models import FakeModelFactory

HEALTH_KEYS = {
    "status",
    "llm",
    "database",
    "langfuse",
    "llm_help_url",
    "langfuse_ui_url",
    "version",
}


async def test_nfr007_health_ok_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == HEALTH_KEYS
    assert body["llm"] == "ok"
    assert body["database"] == "ok"
    assert body["langfuse"] == "disabled"  # tests run with LANGFUSE_ENABLED=false
    assert body["status"] == "ok"  # "disabled" is a deliberate choice, not a degradation


@pytest.mark.parametrize("llm_state", ["missing", "invalid", "unreachable"])
async def test_nfr007_app_starts_and_reports_bad_key(
    make_client: ClientFactory,
    llm_state: CheckResult,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with make_client(model_factory=FakeModelFactory(check_result=llm_state)) as client:
        body = (await client.get("/api/health")).json()
    assert body["llm"] == llm_state
    assert body["status"] == "degraded"
    assert any("LLM" in r.getMessage() and llm_state in r.getMessage() for r in caplog.records)


async def test_nfr007_database_unreachable_is_reported(
    make_client: ClientFactory, settings: Settings
) -> None:
    broken = settings.model_copy(
        update={"database_url": "postgresql+psycopg://nobody:wrong@127.0.0.1:1/none"}
    )
    async with make_client(settings=broken) as client:
        body = (await client.get("/api/health")).json()
    assert body["database"] == "unreachable"
    assert body["status"] == "degraded"


class UnreachableLangfuse(LangfuseClient):
    async def check(self) -> LangfuseState:
        return "unreachable"


async def test_nfr007_langfuse_unreachable_degrades_but_does_not_block(
    make_client: ClientFactory, settings: Settings
) -> None:
    async with make_client(langfuse=UnreachableLangfuse(settings)) as client:
        body = (await client.get("/api/health")).json()
    assert body["langfuse"] == "unreachable"
    assert body["llm"] == "ok" and body["database"] == "ok"
    assert body["status"] == "degraded"


async def test_capture_tracer_fixture_records_runs(capture_tracer: CaptureTracer) -> None:
    """T021: the recorder stands in for Langfuse and captures trace metadata."""
    from langchain_core.runnables import RunnableLambda

    config = capture_tracer.run_config("chat", session_id="conv-9", metadata={"k": "v"})

    def add_one(x: int) -> int:
        return x + 1

    RunnableLambda(add_one).invoke(1, config=config)
    assert config["metadata"]["langfuse_session_id"] == "conv-9"
    kinds = [e.kind for e in capture_tracer.handlers[0].events]
    assert kinds[:2] == ["chain_start", "chain_end"]
    assert await capture_tracer.check() == "ok"
