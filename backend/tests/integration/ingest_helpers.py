"""Shared helpers for ingestion integration tests."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

TERMINAL = {"ready", "failed"}


async def upload_zip(
    client: httpx.AsyncClient, data: bytes, name: str = "repo.zip"
) -> dict[str, Any]:
    response = await client.post(
        "/api/codebases/zip", files={"file": (name, data, "application/zip")}
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def wait_for(
    client: httpx.AsyncClient, codebase_id: str, statuses: set[str] = TERMINAL, seconds: float = 30
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        body: dict[str, Any] = (await client.get(f"/api/codebases/{codebase_id}")).json()
        if body["status"] in statuses:
            return body
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {statuses}: {body}")
        await asyncio.sleep(0.05)


async def wait_until(
    client: httpx.AsyncClient, codebase_id: str, predicate: Any, seconds: float = 30
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        body: dict[str, Any] = (await client.get(f"/api/codebases/{codebase_id}")).json()
        if predicate(body):
            return body
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out: {body}")
        await asyncio.sleep(0.05)
