"""Initial schema per data-model.md (task T019).

The vector dimension comes from EMBEDDING_DIM at migration time. Changing it later needs a new
migration and a re-ingest of every codebase (research R5).

Revision ID: 0001
Revises:
Create Date: 2026-11-16 09:10:52.790631
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from codecompass.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    embedding_dim = get_settings().embedding_dim
    op.create_table(
        "codebase",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("active_ingestion_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source_type IN ('github', 'zip')", name="ck_source_type_enum"),
        sa.CheckConstraint(
            "status IN ('queued', 'ingesting', 'ready', 'failed')", name="ck_status_enum"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("codebase_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(title) <= 80", name="ck_conversation_title_len"),
        sa.ForeignKeyConstraint(["codebase_id"], ["codebase.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_codebase_id"), "conversation", ["codebase_id"], unique=False
    )
    op.create_table(
        "ingestion",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("codebase_id", sa.UUID(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("files_total", sa.Integer(), nullable=False),
        sa.Column("files_done", sa.Integer(), nullable=False),
        sa.Column("chunks_total", sa.Integer(), nullable=False),
        sa.Column("chunks_done", sa.Integer(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overview", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("langfuse_trace_id", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "stage IN ('downloading', 'filtering', 'chunking', 'embedding', 'overview', 'finalizing')",
            name="ck_stage_enum",
        ),
        sa.CheckConstraint("status IN ('running', 'complete', 'failed')", name="ck_status_enum"),
        sa.ForeignKeyConstraint(["codebase_id"], ["codebase.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_codebase_id"), "ingestion", ["codebase_id"], unique=False)
    # Codebase and Ingestion reference each other, so this FK is added after both tables exist.
    op.create_foreign_key(
        "fk_codebase_active_ingestion",
        "codebase",
        "ingestion",
        ["active_ingestion_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "file",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingestion_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("redaction_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingestion_id", "path", name="uq_file_ingestion_path"),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("feedback", sa.SmallInteger(), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_role_enum"),
        sa.CheckConstraint(
            "status IN ('complete', 'error', 'declined', 'not_found')", name="ck_status_enum"
        ),
        sa.CheckConstraint("feedback IS NULL OR feedback IN (1, -1)", name="ck_message_feedback"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_message_conversation_seq"),
    )
    op.create_table(
        "chunk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ingestion_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("symbol_leaf", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("identifiers", sa.Text(), nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(text, '') || ' ' || coalesce(identifiers, '') || ' ' || path)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("embedding", Vector(embedding_dim), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("injection_flag", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('function', 'class', 'method', 'module', 'section', 'window')",
            name="ck_kind_enum",
        ),
        sa.CheckConstraint("start_line >= 1 AND end_line >= start_line", name="ck_chunk_lines"),
        sa.ForeignKeyConstraint(["file_id"], ["file.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunk_ingestion", "chunk", ["ingestion_id"], unique=False)
    op.create_index("ix_chunk_search", "chunk", ["search"], unique=False, postgresql_using="gin")
    op.create_index("ix_chunk_symbol", "chunk", ["symbol"], unique=False)
    op.create_index("ix_chunk_symbol_leaf", "chunk", ["symbol_leaf"], unique=False)
    op.create_index("ix_chunk_symbol_lower", "chunk", [sa.text("lower(symbol)")], unique=False)
    op.create_table(
        "citation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("start_line >= 1 AND end_line >= start_line", name="ck_citation_lines"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunk.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_citation_message_id"), "citation", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_citation_message_id"), table_name="citation")
    op.drop_table("citation")
    op.drop_index("ix_chunk_symbol_lower", table_name="chunk")
    op.drop_index("ix_chunk_symbol_leaf", table_name="chunk")
    op.drop_index("ix_chunk_symbol", table_name="chunk")
    op.drop_index("ix_chunk_search", table_name="chunk", postgresql_using="gin")
    op.drop_index("ix_chunk_ingestion", table_name="chunk")
    op.drop_table("chunk")
    op.drop_table("message")
    op.drop_table("file")
    op.drop_constraint("fk_codebase_active_ingestion", "codebase", type_="foreignkey")
    op.drop_index(op.f("ix_ingestion_codebase_id"), table_name="ingestion")
    op.drop_table("ingestion")
    op.drop_index(op.f("ix_conversation_codebase_id"), table_name="conversation")
    op.drop_table("conversation")
    op.drop_table("codebase")
