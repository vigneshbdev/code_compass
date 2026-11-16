"""FR-020 / FR-021: overview endpoint (task T149)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from tests.fixtures import repos
from tests.integration.chat_helpers import ingest, repo_zip


async def test_fr020_overview_after_ingestion(client: httpx.AsyncClient, tmp_path: Path) -> None:
    codebase = await ingest(client, repo_zip(repos.mini_python_repo, tmp_path))
    response = await client.get(f"/api/codebases/{codebase}/overview")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"languages", "dependencies", "starter_questions", "starter_source"}
    assert body["languages"][0]["language"] == "python"
    assert any(d["name"] == "fastapi" for d in body["dependencies"])
    assert 3 <= len(body["starter_questions"]) <= 5


async def test_fr020_overview_unknown_codebase(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/codebases/{uuid.uuid4()}/overview")
    assert response.status_code == 404
