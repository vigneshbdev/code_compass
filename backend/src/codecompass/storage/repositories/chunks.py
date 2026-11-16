"""Bulk writes of files and chunks with embeddings (T053)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.storage.models import Chunk, File


async def insert_files(
    session: AsyncSession, ingestion_id: uuid.UUID, files: Sequence[dict[str, Any]]
) -> dict[str, int]:
    """Insert File rows; return {path: file_id}."""
    if not files:
        return {}
    rows = [{"ingestion_id": ingestion_id, **f} for f in files]
    result = await session.execute(insert(File).returning(File.id, File.path), rows)
    return {path: file_id for file_id, path in result.all()}


async def insert_chunks(
    session: AsyncSession, ingestion_id: uuid.UUID, chunks: Sequence[dict[str, Any]]
) -> None:
    if chunks:
        await session.execute(insert(Chunk), [{"ingestion_id": ingestion_id, **c} for c in chunks])


async def file_content(session: AsyncSession, ingestion_id: uuid.UUID, path: str) -> File | None:
    result = await session.execute(
        select(File).where(File.ingestion_id == ingestion_id, File.path == path)
    )
    return result.scalar_one_or_none()
