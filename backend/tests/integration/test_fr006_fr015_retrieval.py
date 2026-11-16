"""FR-006 / FR-015: retrieval on real Postgres stays in the selected codebase (task T141)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from codecompass.config import Settings
from codecompass.retrieval.hybrid import HybridRetriever
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for


async def _ingested(client: httpx.AsyncClient, data: bytes) -> uuid.UUID:
    created = await upload_zip(client, data)
    await wait_for(client, created["id"])
    async with client.app.state.db.sessions() as session:  # type: ignore[attr-defined]
        from codecompass.storage.repositories import codebases

        codebase = await codebases.get(session, created["id"])
        assert codebase.active_ingestion_id is not None
        return codebase.active_ingestion_id


async def test_fr015_identifier_query_returns_defining_chunk_first(
    client: httpx.AsyncClient, settings: Settings, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    ingestion = await _ingested(client, repos.zip_dir(repos.mini_python_repo(tmp_path)))
    retriever = HybridRetriever(client.app.state.db.sessions, fake_models.embeddings(), settings)  # type: ignore[attr-defined]
    result = await retriever.retrieve("What does it do?", ["parse_config"], ingestion)
    top = result.packed[0].metadata
    assert top["path"] == "app/core/config.py" and top["symbol"] == "parse_config"
    assert top["symbol_hit"] is True
    assert result.found


async def test_fr006_retrieval_never_crosses_codebases(
    client: httpx.AsyncClient, settings: Settings, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    py = await _ingested(client, repos.zip_dir(repos.mini_python_repo(tmp_path / "py")))
    ts = await _ingested(client, repos.zip_dir(repos.mini_ts_repo(tmp_path / "ts")))
    retriever = HybridRetriever(client.app.state.db.sessions, fake_models.embeddings(), settings)  # type: ignore[attr-defined]
    py_result = await retriever.retrieve("health endpoint status ok", ["health"], py)
    ts_result = await retriever.retrieve("health endpoint status ok", ["health"], ts)
    assert py_result.ranked and ts_result.ranked
    assert all(not d.metadata["path"].startswith("src/") for d in py_result.ranked)
    assert all(d.metadata["path"].startswith(("src/", "package.json")) for d in ts_result.ranked)


async def test_fr013_unrelated_question_fails_precheck(
    client: httpx.AsyncClient, settings: Settings, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    ingestion = await _ingested(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
    strict = settings.model_copy(update={"retrieval_min_score": 0.99})
    retriever = HybridRetriever(client.app.state.db.sessions, fake_models.embeddings(), strict)  # type: ignore[attr-defined]
    result = await retriever.retrieve("kafka zookeeper broker", [], ingestion)
    assert result.found is False and result.packed == []
