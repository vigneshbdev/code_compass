"""Streaming chat endpoint (FR-010, contracts/http-api.md "Chat", task T143)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from codecompass.api.schemas import ChatIn
from codecompass.chat.service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/conversations/{conversation_id}/messages")
async def post_message(conversation_id: str, body: ChatIn, request: Request) -> StreamingResponse:
    service: ChatService = request.app.state.chat
    ctx = await service.prepare(conversation_id)  # 404 / 409 as JSON before streaming starts

    async def events() -> AsyncIterator[str]:
        async for event in service.stream(ctx, body.content.strip()):
            yield event.sse()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
