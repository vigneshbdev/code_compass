"""Analysis U1: a codebase indexed with another embedding model must be re-ingested (T139)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from codecompass.api.errors import AppError, ErrorCode
from codecompass.config import Settings
from codecompass.storage.repositories.codebases import ensure_chat_ready
from tests.conftest import ClientFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for


async def test_u1_reingest_required_after_model_change(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    async with make_client() as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
        assert (await wait_for(client, created["id"]))["reingest_required"] is False

    for change in ({"embedding_model": "fake/other-embed"}, {"embedding_dim": 32}):
        changed = settings.model_copy(update=change)
        async with make_client(settings=changed) as client:
            body = (await client.get(f"/api/codebases/{created['id']}")).json()
            assert body["reingest_required"] is True, change
            app = client.app  # type: ignore[attr-defined]
            async with app.state.db.sessions() as session:
                with pytest.raises(AppError) as info:
                    await ensure_chat_ready(session, created["id"], changed)
            assert info.value.code is ErrorCode.CODEBASE_NOT_READY
            assert "Re-ingest" in info.value.message


async def test_u1_matching_codebase_is_chat_ready(
    client: httpx.AsyncClient,
    settings: Settings,
    tmp_path: Path,
) -> None:
    created = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
    await wait_for(client, created["id"])
    async with client.app.state.db.sessions() as session:  # type: ignore[attr-defined]
        codebase = await ensure_chat_ready(session, created["id"], settings)
    assert str(codebase.id) == created["id"]
