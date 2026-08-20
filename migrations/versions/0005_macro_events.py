"""Persist manually submitted macro events for audit and replay."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_macro_events"
down_revision: str | None = "0004_align_bootstrap_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "macro_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("scheduled_at", sa.String(32), nullable=False),
        sa.Column("consensus", sa.Float(), nullable=False),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("surprise", sa.Float(), nullable=True),
        sa.Column("entered_by", sa.String(32), nullable=False),
        sa.Column("raw", _JSON, nullable=False),
        sa.Column("ingested_at", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_macro_events_type_scheduled",
        "macro_events",
        ["event_type", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_macro_events_type_scheduled", table_name="macro_events")
    op.drop_table("macro_events")
