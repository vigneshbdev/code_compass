"""FR-006 / FR-007 + restart edge case: codebase lifecycle (task T043)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from codecompass.config import Settings
from codecompass.storage.models import Chunk, Codebase, File, Ingestion
from tests.conftest import ClientFactory
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for, wait_until


async def _count(settings: Settings, model: type, **where: object) -> int:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        stmt = select(func.count()).select_from(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        n = (await conn.execute(stmt)).scalar_one()
    await engine.dispose()
    return int(n)


async def test_fr006_list_newest_first(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client() as client:
        a = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path / "a")), "first.zip")
        await wait_for(client, a["id"])
        b = await upload_zip(
            client, repos.zip_dir(repos.mini_ts_repo(tmp_path / "b")), "second.zip"
        )
        await wait_for(client, b["id"])
        items = (await client.get("/api/codebases")).json()["items"]
    assert [i["name"] for i in items] == ["second", "first"]


async def test_fr007_delete_cascades(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    async with make_client() as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
        await wait_for(client, created["id"])
        assert await _count(settings, Chunk) > 0
        response = await client.delete(f"/api/codebases/{created['id']}")
        assert response.status_code == 204
        assert (await client.get(f"/api/codebases/{created['id']}")).status_code == 404
    for model in (File, Chunk, Ingestion):
        assert await _count(settings, model) == 0


async def test_fr007_delete_while_ingesting_is_refused_and_ingestions_are_serialised(
    make_client: ClientFactory, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    fake_models.embedder.gate = asyncio.Event()  # hold the first ingestion in "embedding"
    async with make_client() as client:
        first = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path / "a")))
        await wait_until(
            client, first["id"], lambda b: b["progress"] and b["progress"]["stage"] == "embedding"
        )
        second = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path / "b")))
        await asyncio.sleep(0.2)
        assert (await client.get(f"/api/codebases/{second['id']}")).json()["status"] == "queued"
        response = await client.delete(f"/api/codebases/{first['id']}")
        assert response.status_code == 409
        fake_models.embedder.gate.set()
        assert (await wait_for(client, first["id"]))["status"] == "ready"
        assert (await wait_for(client, second["id"]))["status"] == "ready"


async def test_fr007_reingest_swaps_atomically(
    make_client: ClientFactory, settings: Settings, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    async with make_client() as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
        first = await wait_for(client, created["id"])
        old_chunks = first["progress"]["chunks_total"]

        fake_models.embedder.gate = asyncio.Event()
        response = await client.post(f"/api/codebases/{created['id']}/reingest")
        assert response.status_code == 202
        await wait_until(client, created["id"], lambda b: b["progress"]["stage"] == "embedding")
        # Old index still complete and active while the new one is being built.
        assert await _count(settings, Ingestion, status="complete") == 1
        fake_models.embedder.gate.set()
        done = await wait_for(client, created["id"])
    assert done["status"] == "ready"
    assert await _count(settings, Ingestion) == 1  # previous ingestion's rows removed
    assert await _count(settings, Chunk) == old_chunks


async def _insert_stuck(settings: Settings, with_previous: bool) -> uuid.UUID:
    """Simulate a restart mid-ingestion: a codebase left `ingesting` with a running ingestion."""
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine)
    codebase_id = uuid.uuid4()
    model = {"embedding_model": settings.embedding_model, "embedding_dim": settings.embedding_dim}
    async with sessions() as session, session.begin():
        session.add(Codebase(id=codebase_id, name="stuck", source_type="zip", status="ingesting"))
        await session.flush()
        if with_previous:
            previous = Ingestion(
                codebase_id=codebase_id, status="complete", stage="finalizing", **model
            )
            session.add(previous)
            await session.flush()
            await session.execute(
                update(Codebase)
                .where(Codebase.id == codebase_id)
                .values(active_ingestion_id=previous.id)
            )
        session.add(
            Ingestion(codebase_id=codebase_id, status="running", stage="embedding", **model)
        )
    await engine.dispose()
    return codebase_id


async def test_edge_restart_mid_ingestion_marks_failed(
    make_client: ClientFactory, settings: Settings
) -> None:
    codebase_id = await _insert_stuck(settings, with_previous=False)
    async with make_client() as client:  # app startup runs recovery
        body = (await client.get(f"/api/codebases/{codebase_id}")).json()
    assert body["status"] == "failed"
    assert "restart" in body["error"].lower()
    assert await _count(settings, Ingestion, status="running") == 0


async def test_edge_restart_mid_reingest_keeps_previous_index(
    make_client: ClientFactory, settings: Settings
) -> None:
    codebase_id = await _insert_stuck(settings, with_previous=True)
    async with make_client() as client:
        body = (await client.get(f"/api/codebases/{codebase_id}")).json()
    assert body["status"] == "ready"
    assert body["error"]
    assert await _count(settings, Ingestion) == 1
