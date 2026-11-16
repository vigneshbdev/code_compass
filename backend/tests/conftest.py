"""Shared test harness (task T021).

- One Postgres + pgvector container per session (testcontainers), migrated with Alembic.
- Tables truncated between tests.
- App fixtures wired with FakeModelFactory and Langfuse disabled: no network, no API key.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from codecompass.config import Settings, get_settings
from codecompass.main import create_app
from codecompass.observability.langfuse_client import LangfuseClient
from tests.fakes.capture_tracer import CaptureTracer
from tests.fakes.fake_models import FakeModelFactory

PG_IMAGE = "pgvector/pgvector:0.8.7-pg16"
TEST_DIM = 64  # small vectors keep tests fast; the migration reads EMBEDDING_DIM
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = "citation, message, conversation, chunk, file, ingestion, codebase"

BASE_ENV = {
    "LLM_MODEL": "fake/answer",
    "LLM_FAST_MODEL": "fake/fast",
    "LLM_JUDGE_MODEL": "fake/judge",
    "EMBEDDING_MODEL": "fake/embed",
    "EMBEDDING_DIM": str(TEST_DIM),
    "LANGFUSE_ENABLED": "false",
}


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(PG_IMAGE, driver="psycopg", dbname="codecompass") as pg:
        url = pg.get_connection_url()
        env = {**BASE_ENV, "DATABASE_URL": url}
        previous = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        get_settings.cache_clear()
        cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
        cfg.attributes["database_url"] = url
        command.upgrade(cfg, "head")
        yield url
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture
def settings(database_url: str, tmp_path: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "no-static",
        max_files=50,
        max_index_bytes=5_000_000,
        embed_batch_size=16,
    )


@pytest.fixture(autouse=True)
async def _clean_tables(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    yield
    if "database_url" not in request.fixturenames:
        return
    url = request.getfixturevalue("database_url")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def capture_tracer(settings: Settings) -> CaptureTracer:
    """Replaces Langfuse with an in-memory recorder. Pass it as `make_client(langfuse=...)`."""
    return CaptureTracer(settings)


@pytest.fixture
def fake_models() -> FakeModelFactory:
    return FakeModelFactory(dim=TEST_DIM)


ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def make_client(settings: Settings, fake_models: FakeModelFactory) -> ClientFactory:
    @asynccontextmanager
    async def _make(
        *,
        settings: Settings = settings,
        model_factory: Any = fake_models,
        langfuse: LangfuseClient | None = None,
    ) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(settings=settings, model_factory=model_factory, langfuse=langfuse)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                client.app = app  # type: ignore[attr-defined]  # tests may reach app.state
                yield client

    return _make


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client() as c:
        yield c
