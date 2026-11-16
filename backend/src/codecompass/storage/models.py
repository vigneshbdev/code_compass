"""SQLAlchemy models, exactly per specs/001-code-assistant/data-model.md (tasks T017, T018).

Enumerations are stored as text with CHECK constraints so values stay readable in SQL and
adding a value is a one-line migration. All foreign keys cascade on delete (FR-007).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _enum_check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_enum")


CODEBASE_STATUS = ("queued", "ingesting", "ready", "failed")
SOURCE_TYPE = ("github", "zip")
INGESTION_STATUS = ("running", "complete", "failed")
INGESTION_STAGE = ("downloading", "filtering", "chunking", "embedding", "overview", "finalizing")
CHUNK_KIND = ("function", "class", "method", "module", "section", "window")
MESSAGE_ROLE = ("user", "assistant")
MESSAGE_STATUS = ("complete", "error", "declined", "not_found", "unverified")  # C4
SKIP_REASONS = (
    "gitignored",
    "denylisted_dir",
    "lockfile",
    "binary",
    "too_large",
    "non_utf8",
    "symlink",
    "unsafe_path",
    "private_key_file",
)


# Lexical index source (research R5): chunk text + split identifiers + path, 'simple' config.
SEARCH_EXPRESSION = (
    "to_tsvector('simple', coalesce(text, '') || ' ' || coalesce(identifiers, '') || ' ' || path)"
)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ── Part 1 (T017): Codebase, Ingestion, File, Chunk ────────────────────────────────────────


class Codebase(Base):
    __tablename__ = "codebase"
    __table_args__ = (
        _enum_check("status", CODEBASE_STATUS),
        _enum_check("source_type", SOURCE_TYPE),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    # use_alter: Codebase ↔ Ingestion reference each other.
    active_ingestion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ingestion.id", ondelete="SET NULL", use_alter=True, name="fk_codebase_active_ingestion"
        ),
    )
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)  # contracts/http-api.md error code
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Ingestion(Base):
    __tablename__ = "ingestion"
    __table_args__ = (
        _enum_check("status", INGESTION_STATUS),
        _enum_check("stage", INGESTION_STAGE),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    codebase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("codebase.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    commit_sha: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    stage: Mapped[str] = mapped_column(Text, nullable=False, default="downloading")
    files_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    overview: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    langfuse_trace_id: Mapped[str | None] = mapped_column(Text)
    # Analysis U1: the model that produced this ingestion's vectors. A mismatch with current
    # settings means the codebase must be re-ingested before chat (no mixed vector spaces).
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class File(Base):
    __tablename__ = "file"
    __table_args__ = (UniqueConstraint("ingestion_id", "path", name="uq_file_ingestion_path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingestion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # redacted; never the original
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = (
        CheckConstraint("start_line >= 1 AND end_line >= start_line", name="ck_chunk_lines"),
        _enum_check("kind", CHUNK_KIND),
        Index("ix_chunk_ingestion", "ingestion_id"),
        Index("ix_chunk_symbol", "symbol"),
        Index("ix_chunk_symbol_lower", text("lower(symbol)")),
        Index("ix_chunk_symbol_leaf", "symbol_leaf"),
        Index("ix_chunk_search", "search", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingestion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    symbol_leaf: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)  # redacted span text
    embed_text: Mapped[str] = mapped_column(Text, nullable=False)
    identifiers: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_EXPRESSION, persisted=True),
    )
    # Dimension is fixed by the migration from EMBEDDING_DIM (research R5).
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    injection_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ── Part 2 (T018): Conversation, Message, Citation ─────────────────────────────────────────


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        CheckConstraint("char_length(title) <= 80", name="ck_conversation_title_len"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()  # also the Langfuse session_id
    codebase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("codebase.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_message_conversation_seq"),
        _enum_check("role", MESSAGE_ROLE),
        _enum_check("status", MESSAGE_STATUS),
        CheckConstraint("feedback IS NULL OR feedback IN (1, -1)", name="ck_message_feedback"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # output-rail-filtered (FR-033)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="complete")
    trace_id: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feedback: Mapped[int | None] = mapped_column(SmallInteger)
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Citation(Base):
    __tablename__ = "citation"
    __table_args__ = (
        CheckConstraint("start_line >= 1 AND end_line >= start_line", name="ck_citation_lines"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("chunk.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
