"""Add latest successful real-ingest snapshots."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_last_good_snapshots"
down_revision: str | None = "0002_total_mcap_samples"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "last_good_snapshots",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("as_of", sa.String(32), nullable=False),
        sa.Column("deviation_flags", _JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("last_good_snapshots")
