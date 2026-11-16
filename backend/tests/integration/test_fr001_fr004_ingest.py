"""FR-001…FR-004, FR-030, U1: ingest a zip end to end (tasks T041, T138)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import create_async_engine

from codecompass.config import Settings
from codecompass.storage.models import Chunk, File, Ingestion
from tests.conftest import ClientFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for

CODEBASE_KEYS = {
    "id",
    "name",
    "source_type",
    "source_url",
    "source_ref",
    "commit_sha",
    "status",
    "error",
    "error_code",
    "reingest_required",
    "progress",
    "summary",
    "created_at",
    "updated_at",
}


async def _rows(settings: Settings, model: type[Any], **where: object) -> list[Any]:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        stmt: Select[Any] = select(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        rows = (await conn.execute(stmt)).all()
    await engine.dispose()
    return list(rows)


async def test_fr002_fr004_zip_upload_is_indexed_with_summary(
    client: httpx.AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    created = await upload_zip(client, repos.zip_dir(repos.mini_python_repo(tmp_path)), "mini.zip")
    assert created["status"] == "queued"
    assert created["name"] == "mini"
    assert created["source_type"] == "zip"

    body = await wait_for(client, created["id"])
    assert body["status"] == "ready", body
    assert set(body) == CODEBASE_KEYS
    assert body["error"] is None and body["reingest_required"] is False

    summary = body["summary"]
    assert summary["indexed"] >= 7
    by_reason = summary["skipped_by_reason"]
    for reason in ("gitignored", "denylisted_dir", "lockfile", "binary", "too_large", "non_utf8"):
        assert by_reason.get(reason, 0) >= 1, reason
    assert {s["path"] for s in summary["skipped"]} >= {"poetry.lock", "logo.png", "node_modules"}
    assert summary["bytes_indexed"] > 0

    progress = body["progress"]
    assert progress["files_done"] == progress["files_total"] == summary["indexed"]
    assert progress["chunks_done"] == progress["chunks_total"] > 0

    files = await _rows(settings, File)
    assert {f.path for f in files} >= {"app/main.py", "app/api/users.py", "README.md"}
    chunks = await _rows(settings, Chunk)
    assert len(chunks) == progress["chunks_total"]
    assert all(len(c.embedding) == settings.embedding_dim for c in chunks)

    (ingestion,) = await _rows(settings, Ingestion)
    assert ingestion.embedding_model == settings.embedding_model  # U1 (T138)
    assert ingestion.embedding_dim == settings.embedding_dim


async def test_fr030_stored_content_has_no_planted_secret(
    client: httpx.AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    created = await upload_zip(client, repos.zip_dir(repos.guardrail_repo(tmp_path)))
    body = await wait_for(client, created["id"])
    assert body["status"] == "ready", body
    reasons = {s["path"]: s["reason"] for s in body["summary"]["skipped"]}
    assert reasons[repos.PRIVATE_KEY_PATH] == "private_key_file"

    stored = "\n".join(f.content for f in await _rows(settings, File))
    stored += "\n".join(c.text + c.embed_text + c.identifiers for c in await _rows(settings, Chunk))
    assert "[REDACTED:" in stored
    for secret in repos.SECRETS:
        assert secret.value not in stored, secret.kind


async def test_fr004_skipped_list_is_capped_at_500(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    repo = tmp_path / "many"
    repo.mkdir()
    (repo / "main.py").write_text("x = 1\n")
    for i in range(600):
        (repo / f"img{i}.png").write_bytes(repos.PNG_1X1)
    created = await upload_zip(client, repos.zip_dir(repo))
    body = await wait_for(client, created["id"])
    assert len(body["summary"]["skipped"]) == 500
    assert body["summary"]["skipped_by_reason"]["binary"] == 600


async def test_fr002_non_zip_upload_is_rejected_immediately(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/codebases/zip", files={"file": ("x.zip", b"not a zip", "application/zip")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_archive"


async def test_fr002_upload_over_limit_is_rejected(
    make_client: ClientFactory,
    settings: Settings,
    tmp_path: Path,
) -> None:
    small = settings.model_copy(update={"max_upload_bytes": 1_000})
    data = repos.zip_dir(repos.mini_python_repo(tmp_path))
    async with make_client(settings=small) as client:
        response = await client.post(
            "/api/codebases/zip", files={"file": ("m.zip", data, "application/zip")}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "repo_too_large"


async def test_fr001_invalid_github_url_is_rejected_immediately(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/codebases/github", json={"url": "https://gitlab.com/o/r"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_github_url"
