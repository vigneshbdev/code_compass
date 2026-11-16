"""Conversation endpoints (FR-014, FR-016, task T143)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.api.schemas import (
    CitationOut,
    ConversationList,
    ConversationOut,
    ConversationSummary,
    MessageOut,
)
from codecompass.observability.langfuse_client import LangfuseClient
from codecompass.storage.db import get_session
from codecompass.storage.models import Citation, Message
from codecompass.storage.repositories import codebases as codebase_repo
from codecompass.storage.repositories import conversations as conversation_repo

router = APIRouter(tags=["conversations"])
Session = Annotated[AsyncSession, Depends(get_session)]


def message_out(m: Message, citations: list[Citation], langfuse: LangfuseClient) -> MessageOut:
    return MessageOut(
        id=str(m.id),
        seq=m.seq,
        role=m.role,
        status=m.status,
        content=m.content,
        citations=[
            CitationOut(path=c.path, start_line=c.start_line, end_line=c.end_line)
            for c in citations
        ],
        trace_id=m.trace_id,
        trace_url=langfuse.trace_url(m.trace_id),
        feedback=m.feedback,
        usage=m.usage,
        created_at=m.created_at,
    )


@router.get("/codebases/{codebase_id}/conversations", response_model=ConversationList)
async def list_conversations(codebase_id: str, session: Session) -> ConversationList:
    codebase = await codebase_repo.get(session, codebase_id)
    rows = await conversation_repo.list_for_codebase(session, codebase.id)
    return ConversationList(
        items=[
            ConversationSummary(
                id=str(c.id),
                title=c.title,
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=n,
            )
            for c, n in rows
        ]
    )


@router.post(
    "/codebases/{codebase_id}/conversations", status_code=201, response_model=ConversationSummary
)
async def create_conversation(codebase_id: str, session: Session) -> ConversationSummary:
    codebase = await codebase_repo.get(session, codebase_id)
    conversation = await conversation_repo.create(session, codebase.id)
    await session.commit()
    await session.refresh(conversation)
    return ConversationSummary(
        id=str(conversation.id),
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=0,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str, session: Session, request: Request
) -> ConversationOut:
    conversation = await conversation_repo.get(session, conversation_id)
    messages = await conversation_repo.messages(session, conversation.id)
    cites = await conversation_repo.citations_for(session, [m.id for m in messages])
    langfuse: LangfuseClient = request.app.state.langfuse
    return ConversationOut(
        id=str(conversation.id),
        codebase_id=str(conversation.codebase_id),
        title=conversation.title,
        messages=[message_out(m, cites.get(m.id, []), langfuse) for m in messages],
    )
