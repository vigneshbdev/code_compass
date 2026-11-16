"""Conversations, messages and citations (FR-016, task T143)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.api.errors import AppError, ErrorCode
from codecompass.storage.models import Citation, Conversation, Message

TITLE_CHARS = 80


def _uuid(value: str | uuid.UUID, what: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise AppError(ErrorCode.NOT_FOUND, f"{what} not found.") from None


async def create(
    session: AsyncSession, codebase_id: uuid.UUID, title: str = "New conversation"
) -> Conversation:
    conversation = Conversation(codebase_id=codebase_id, title=title[:TITLE_CHARS])
    session.add(conversation)
    await session.flush()
    return conversation


async def get(session: AsyncSession, conversation_id: str | uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, _uuid(conversation_id, "Conversation"))
    if conversation is None:
        raise AppError(ErrorCode.NOT_FOUND, "Conversation not found.")
    return conversation


async def list_for_codebase(
    session: AsyncSession, codebase_id: uuid.UUID
) -> list[tuple[Conversation, int]]:
    counts = (
        select(Message.conversation_id, func.count().label("n"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    stmt = (
        select(Conversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.codebase_id == codebase_id)
        .order_by(Conversation.updated_at.desc())
    )
    return [(c, int(n)) for c, n in (await session.execute(stmt)).all()]


async def messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    return list((await session.execute(stmt)).scalars())


async def citations_for(
    session: AsyncSession, message_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Citation]]:
    if not message_ids:
        return {}
    stmt = select(Citation).where(Citation.message_id.in_(message_ids)).order_by(Citation.ordinal)
    grouped: dict[uuid.UUID, list[Citation]] = {}
    for c in (await session.execute(stmt)).scalars():
        grouped.setdefault(c.message_id, []).append(c)
    return grouped


async def add_message(session: AsyncSession, conversation_id: uuid.UUID, **fields: Any) -> Message:
    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ).scalar_one()
    message = Message(conversation_id=conversation_id, seq=int(next_seq), **fields)
    session.add(message)
    await session.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(updated_at=func.now())
    )
    await session.flush()
    return message


async def set_title_if_new(
    session: AsyncSession, conversation: Conversation, question: str
) -> None:
    if conversation.title == "New conversation":
        conversation.title = " ".join(question.split())[:TITLE_CHARS] or conversation.title


async def add_citations(
    session: AsyncSession, message_id: uuid.UUID, rows: Sequence[dict[str, Any]]
) -> None:
    for row in rows:
        session.add(Citation(message_id=message_id, **row))


async def get_message(session: AsyncSession, message_id: str | uuid.UUID) -> Message:
    message = await session.get(Message, _uuid(message_id, "Message"))
    if message is None:
        raise AppError(ErrorCode.NOT_FOUND, "Message not found.")
    return message


async def trace_ids_for_codebase(session: AsyncSession, codebase_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Message.trace_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.codebase_id == codebase_id, Message.trace_id.is_not(None))
    )
    return [t for t in (await session.execute(stmt)).scalars() if t]
