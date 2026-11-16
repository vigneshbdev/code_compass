"""Answer feedback (FR-041, task T146)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.api.errors import AppError, ErrorCode
from codecompass.api.schemas import FeedbackIn
from codecompass.observability.langfuse_client import LangfuseClient
from codecompass.storage.db import get_session
from codecompass.storage.repositories import conversations as conversation_repo

router = APIRouter(tags=["feedback"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.put("/messages/{message_id}/feedback", status_code=204)
async def put_feedback(
    message_id: str, body: FeedbackIn, session: Session, request: Request
) -> Response:
    message = await conversation_repo.get_message(session, message_id)
    if message.role != "assistant":
        raise AppError(ErrorCode.NOT_FOUND, "Feedback applies to assistant answers only.")
    message.feedback = body.value
    message.feedback_comment = body.comment
    await session.commit()
    langfuse: LangfuseClient = request.app.state.langfuse
    if message.trace_id and body.value is not None:
        langfuse.score(message.trace_id, "user_feedback", body.value, body.comment)
    return Response(status_code=204)
