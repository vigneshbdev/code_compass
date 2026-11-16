"""FR-005 / NFR-004: over-limit repos are rejected and nothing is partially indexed (T042)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from codecompass.config import Settings
from codecompass.storage.models import Chunk, File, Ingestion
from tests.conftest import ClientFactory
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for


async def _count(settings: Settings, model: type) -> int:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        n = (await conn.execute(select(func.count()).select_from(model))).scalar_one()
    await engine.dispose()
    return int(n)


async def test_fr005_too_many_files_is_rejected_before_embedding(
    make_client: ClientFactory, settings: Settings, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    limited = settings.model_copy(update={"max_files": 3})
    async with make_client(settings=limited) as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_python_repo(tmp_path)))
        body = await wait_for(client, created["id"])
    assert body["status"] == "failed"
    assert body["error_code"] == "repo_too_large"
    assert "3" in body["error"] and "files" in body["error"]
    assert fake_models.embedder.calls == 0  # rejected before any embedding
    for model in (File, Chunk, Ingestion):
        assert await _count(settings, model) == 0, model.__name__


async def test_fr005_too_many_bytes_is_rejected(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    limited = settings.model_copy(update={"max_index_bytes": 500})
    async with make_client(settings=limited) as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_python_repo(tmp_path)))
        body = await wait_for(client, created["id"])
    assert body["status"] == "failed" and body["error_code"] == "repo_too_large"
    assert await _count(settings, Chunk) == 0


async def test_edge_no_supported_files(make_client: ClientFactory, tmp_path: Path) -> None:
    repo = tmp_path / "binaries"
    repo.mkdir()
    (repo / "logo.png").write_bytes(repos.PNG_1X1)
    async with make_client() as client:
        created = await upload_zip(client, repos.zip_dir(repo))
        body = await wait_for(client, created["id"])
    assert body["status"] == "failed"
    assert body["error_code"] == "no_supported_files"
