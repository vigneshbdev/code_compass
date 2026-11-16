"""Response/request models for contracts/http-api.md (task T055)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from codecompass.config import Settings
from codecompass.storage.models import Codebase, Ingestion
from codecompass.storage.repositories.codebases import reingest_required


class Progress(BaseModel):
    stage: str
    files_done: int
    files_total: int
    chunks_done: int
    chunks_total: int


class SkipOut(BaseModel):
    path: str
    reason: str


class Summary(BaseModel):
    indexed: int
    skipped: list[SkipOut]
    skipped_by_reason: dict[str, int]
    bytes_indexed: int


class CodebaseOut(BaseModel):
    id: str
    name: str
    source_type: Literal["github", "zip"]
    source_url: str | None
    source_ref: str | None
    commit_sha: str | None
    status: Literal["queued", "ingesting", "ready", "failed"]
    error: str | None
    error_code: str | None
    reingest_required: bool
    progress: Progress | None
    summary: Summary | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        codebase: Codebase,
        active: Ingestion | None,
        latest: Ingestion | None,
        settings: Settings,
    ) -> CodebaseOut:
        """`progress` follows the newest ingestion; `summary` comes from the active index."""
        shown = latest or active
        progress = (
            Progress(
                stage=shown.stage,
                files_done=shown.files_done,
                files_total=shown.files_total,
                chunks_done=shown.chunks_done,
                chunks_total=shown.chunks_total,
            )
            if shown is not None
            else None
        )
        summary_data: dict[str, Any] | None = active.summary if active is not None else None
        source = active or latest
        return cls(
            id=str(codebase.id),
            name=codebase.name,
            source_type=codebase.source_type,
            source_url=codebase.source_url,
            source_ref=codebase.source_ref,
            commit_sha=source.commit_sha if source is not None else None,
            status=codebase.status,
            error=codebase.error,
            error_code=codebase.error_code,
            reingest_required=reingest_required(active, settings),
            progress=progress,
            summary=Summary.model_validate(summary_data) if summary_data else None,
            created_at=codebase.created_at,
            updated_at=codebase.updated_at,
        )


class CodebaseList(BaseModel):
    items: list[CodebaseOut]


class GithubIn(BaseModel):
    url: str
    ref: str | None = None


# ── Conversations and messages (contracts/http-api.md "Conversations", T143) ──────────────


class CitationOut(BaseModel):
    path: str
    start_line: int
    end_line: int


class MessageOut(BaseModel):
    id: str
    seq: int
    role: Literal["user", "assistant"]
    status: Literal["complete", "error", "declined", "not_found", "unverified"]
    content: str
    citations: list[CitationOut]
    trace_id: str | None
    trace_url: str | None
    feedback: int | None
    usage: dict[str, Any] | None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationList(BaseModel):
    items: list[ConversationSummary]


class ConversationOut(BaseModel):
    id: str
    codebase_id: str
    title: str
    messages: list[MessageOut]


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class FeedbackIn(BaseModel):
    value: Literal[1, -1] | None
    comment: str | None = Field(default=None, max_length=2000)


class FileOut(BaseModel):
    path: str
    language: str
    line_count: int
    content: str
    redaction_count: int
