"""Align Alembic indexes with the SQLAlchemy metadata used by legacy create_all databases."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_align_bootstrap_schema"
down_revision: str | None = "0003_last_good_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_call_records_provider_created", table_name="call_records")
    op.create_index("ix_call_records_provider", "call_records", ["provider"])
    op.create_index("ix_call_records_created_at", "call_records", ["created_at"])
    op.drop_index(
        "ix_total_mcap_samples_symbol_as_of",
        table_name="total_mcap_samples",
    )


def downgrade() -> None:
    op.create_index(
        "ix_total_mcap_samples_symbol_as_of",
        "total_mcap_samples",
        ["symbol", "as_of"],
    )
    op.drop_index("ix_call_records_created_at", table_name="call_records")
    op.drop_index("ix_call_records_provider", table_name="call_records")
    op.create_index(
        "ix_call_records_provider_created",
        "call_records",
        ["provider", "created_at"],
    )
