"""Helpers for chat integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from codecompass.storage.models import Chunk
from tests.integration.ingest_helpers import upload_zip, wait_for


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def ingest(client: httpx.AsyncClient, data: bytes) -> str:
    created = await upload_zip(client, data)
    body = await wait_for(client, created["id"])
    assert body["status"] == "ready", body
    return str(created["id"])


async def new_conversation(client: httpx.AsyncClient, codebase_id: str) -> str:
    response = await client.post(f"/api/codebases/{codebase_id}/conversations")
    assert response.status_code == 201
    return str(response.json()["id"])


async def ask(
    client: httpx.AsyncClient, conversation_id: str, question: str
) -> list[tuple[str, dict[str, Any]]]:
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": question}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def text_of(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(d["text"] for e, d in events if e == "token")


async def chunk_span(client: httpx.AsyncClient, symbol: str) -> tuple[str, int, int]:
    async with client.app.state.db.sessions() as session:  # type: ignore[attr-defined]
        chunk = (
            (await session.execute(select(Chunk).where(Chunk.symbol == symbol))).scalars().first()
        )
    assert chunk is not None
    return chunk.path, chunk.start_line, chunk.end_line


def repo_zip(builder: Any, tmp_path: Path) -> bytes:
    from tests.fixtures import repos

    return repos.zip_dir(builder(tmp_path))
