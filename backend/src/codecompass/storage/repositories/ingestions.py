"""Ingestion rows: progress, atomic activation, cleanup (T052, research R14)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.storage.models import Codebase, Ingestion

RESTART_MESSAGE = "Ingestion was interrupted by a restart. Retry to index it again."


async def create(session: AsyncSession, codebase_id: uuid.UUID, **fields: Any) -> Ingestion:
    ingestion = Ingestion(codebase_id=codebase_id, status="running", stage="downloading", **fields)
    session.add(ingestion)
    await session.flush()
    return ingestion


async def update_progress(session: AsyncSession, ingestion_id: uuid.UUID, **fields: Any) -> None:
    await session.execute(update(Ingestion).where(Ingestion.id == ingestion_id).values(**fields))


async def latest(session: AsyncSession, codebase_id: uuid.UUID) -> Ingestion | None:
    """Most recent ingestion (running or not), used for progress and summary display."""
    result = await session.execute(
        select(Ingestion)
        .where(Ingestion.codebase_id == codebase_id)
        .order_by(Ingestion.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def activate(session: AsyncSession, codebase_id: uuid.UUID, ingestion_id: uuid.UUID) -> None:
    """Single transaction: point the codebase at the new index, then drop the old one (R14)."""
    await session.execute(
        update(Ingestion)
        .where(Ingestion.id == ingestion_id)
        .values(status="complete", stage="finalizing", finished_at=func.now())
    )
    await session.execute(
        update(Codebase)
        .where(Codebase.id == codebase_id)
        .values(active_ingestion_id=ingestion_id, status="ready", error=None, error_code=None)
    )
    # Cascades remove the previous ingestion's files and chunks.
    await session.execute(
        delete(Ingestion).where(Ingestion.codebase_id == codebase_id, Ingestion.id != ingestion_id)
    )


async def discard(session: AsyncSession, ingestion_id: uuid.UUID) -> None:
    await session.execute(delete(Ingestion).where(Ingestion.id == ingestion_id))


async def unfinished(session: AsyncSession) -> list[Ingestion]:
    result = await session.execute(select(Ingestion).where(Ingestion.status == "running"))
    return list(result.scalars())


async def stuck_codebases(session: AsyncSession) -> list[Codebase]:
    result = await session.execute(
        select(Codebase).where(Codebase.status.in_(("queued", "ingesting")))
    )
    return list(result.scalars())
