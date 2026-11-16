"""Record the embedding model per ingestion (analysis U1); add `unverified` status (C4);
store the machine-readable failure code on codebases (T042).

Task T138. 0001 is never edited because it has already run on existing databases.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUS = "status IN ('complete', 'error', 'declined', 'not_found')"
NEW_STATUS = "status IN ('complete', 'error', 'declined', 'not_found', 'unverified')"


def upgrade() -> None:
    # Existing rows predate tracking; mark them unknown so they report reingest_required.
    op.add_column("ingestion", sa.Column("embedding_model", sa.Text(), nullable=True))
    op.add_column("ingestion", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.execute("UPDATE ingestion SET embedding_model = 'unknown', embedding_dim = 0")
    op.alter_column("ingestion", "embedding_model", nullable=False)
    op.alter_column("ingestion", "embedding_dim", nullable=False)

    op.drop_constraint("ck_status_enum", "message", type_="check")
    op.create_check_constraint("ck_status_enum", "message", NEW_STATUS)

    op.add_column("codebase", sa.Column("error_code", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("codebase", "error_code")
    op.execute("UPDATE message SET status = 'complete' WHERE status = 'unverified'")
    op.drop_constraint("ck_status_enum", "message", type_="check")
    op.create_check_constraint("ck_status_enum", "message", OLD_STATUS)
    op.drop_column("ingestion", "embedding_dim")
    op.drop_column("ingestion", "embedding_model")
