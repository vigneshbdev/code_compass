"""Codebase persistence and readiness rules (T052, T139)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.api.errors import AppError, ErrorCode
from codecompass.config import Settings
from codecompass.storage.models import Codebase, Ingestion

IN_PROGRESS = ("queued", "ingesting")
REINGEST_MESSAGE = "The embedding model changed since this codebase was indexed. Re-ingest it."


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise AppError(ErrorCode.NOT_FOUND, "Codebase not found.") from None


async def create(session: AsyncSession, **fields: Any) -> Codebase:
    codebase = Codebase(status="queued", **fields)
    session.add(codebase)
    await session.flush()
    return codebase


async def get(session: AsyncSession, codebase_id: str | uuid.UUID) -> Codebase:
    codebase = await session.get(Codebase, _uuid(codebase_id))
    if codebase is None:
        raise AppError(ErrorCode.NOT_FOUND, "Codebase not found.")
    return codebase


async def list_all(session: AsyncSession) -> list[Codebase]:
    result = await session.execute(
        select(Codebase).order_by(Codebase.created_at.desc(), Codebase.id)
    )
    return list(result.scalars())


async def set_status(
    session: AsyncSession,
    codebase_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
    error_code: str | None = None,
) -> None:
    await session.execute(
        update(Codebase)
        .where(Codebase.id == codebase_id)
        .values(status=status, error=error, error_code=error_code)
    )


async def delete_codebase(session: AsyncSession, codebase: Codebase) -> None:
    if codebase.status in IN_PROGRESS:
        raise AppError(
            ErrorCode.CODEBASE_NOT_READY, "Wait for ingestion to finish before deleting."
        )
    await session.execute(delete(Codebase).where(Codebase.id == codebase.id))


def reingest_required(active: Ingestion | None, settings: Settings) -> bool:
    """U1: vectors from another embedding model or dimension must not be queried."""
    if active is None:
        return False
    return (
        active.embedding_model != settings.embedding_model
        or active.embedding_dim != settings.embedding_dim
    )


async def ensure_chat_ready(
    session: AsyncSession, codebase_id: str | uuid.UUID, settings: Settings
) -> Codebase:
    """Raise `codebase_not_ready` unless chat can safely use this codebase (FR-006, U1)."""
    codebase = await get(session, codebase_id)
    if codebase.active_ingestion_id is None:
        raise AppError(ErrorCode.CODEBASE_NOT_READY, "This codebase is not indexed yet.")
    active = await session.get(Ingestion, codebase.active_ingestion_id)
    if reingest_required(active, settings):
        raise AppError(ErrorCode.CODEBASE_NOT_READY, REINGEST_MESSAGE)
    return codebase
