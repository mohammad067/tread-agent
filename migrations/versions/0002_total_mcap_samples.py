"""Add deduplicated TOTAL_MCAP history samples."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_total_mcap_samples"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "total_mcap_samples",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("as_of", sa.String(32), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("run_id", sa.String(26), nullable=True),
    )
    op.create_index(
        "ix_total_mcap_samples_symbol_as_of",
        "total_mcap_samples",
        ["symbol", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_total_mcap_samples_symbol_as_of",
        table_name="total_mcap_samples",
    )
    op.drop_table("total_mcap_samples")
