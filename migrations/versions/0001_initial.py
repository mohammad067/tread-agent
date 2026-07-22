"""0001 initial — all MVP tables (database.md §B.1, api-db-fixtures Part B).

Creates every table from the frozen DB design, including the M2 field additions on ``runs``
(is_degraded, provider_version, model_version, pricing_version) and the indexes in §B.3. JSON columns
use the portable variant (JSON on SQLite, JSONB on Postgres) so the one migration runs on both
dialects (ADR-006). Append-only tables have no distinct migration treatment — append-only is enforced
in the repository layer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Portable JSON: JSONB on Postgres, JSON elsewhere — matches persistence/models.py.
_JSON = sa.JSON().with_variant(JSONB(), "postgresql")
_ULID = sa.String(26)
_VERSION = sa.String(64)
_TS = sa.String(32)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", _ULID, primary_key=True),
        sa.Column("run_sequence", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("trigger_detail", _JSON, nullable=False),
        sa.Column("generated_at", _TS, nullable=False),
        sa.Column("schema_version", _VERSION, nullable=False),
        sa.Column("pipeline_version", _VERSION, nullable=False),
        sa.Column("provider_version", _VERSION, nullable=True),
        sa.Column("model_version", _VERSION, nullable=True),
        sa.Column("prompt_sentiment_version", _VERSION, nullable=False),
        sa.Column("prompt_synthesis_version", _VERSION, nullable=False),
        sa.Column("rulebook_version", _VERSION, nullable=False),
        sa.Column("mhi_weights_version", _VERSION, nullable=False),
        sa.Column("pricing_version", _VERSION, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_runs_run_sequence", "runs", ["run_sequence"])
    op.create_index("ix_runs_generated_at", "runs", ["generated_at"])
    op.create_index("ix_runs_trigger_type", "runs", ["trigger_type"])

    op.create_table(
        "run_inputs",
        sa.Column("run_id", _ULID, primary_key=True),
        sa.Column("raw_snapshots", _JSON, nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("data_gaps", _JSON, nullable=False),
        sa.Column("deviation_flags", _JSON, nullable=False),
        sa.Column("ingested_at", _TS, nullable=False),
    )

    op.create_table(
        "run_outputs",
        sa.Column("run_id", _ULID, primary_key=True),
        sa.Column("market_state_run", _JSON, nullable=False),
        sa.Column("guardrail_flags", _JSON, nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("persisted_at", _TS, nullable=False),
    )

    op.create_table(
        "call_records",
        sa.Column("call_id", _ULID, primary_key=True),
        sa.Column("run_id", _ULID, nullable=False),
        sa.Column("llm_job", sa.String(16), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", _VERSION, nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("rendered_prompt", sa.Text(), nullable=False),
        sa.Column("response", _JSON, nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("finish_reason", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_call_records_run_id", "call_records", ["run_id"])
    op.create_index("ix_call_records_provider_created", "call_records", ["provider", "created_at"])

    op.create_table(
        "event_log",
        sa.Column("event_seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", _ULID, nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_event_log_run_id", "event_log", ["run_id"])
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])

    op.create_table(
        "news_items",
        sa.Column("news_id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_at", _TS, nullable=False),
        sa.Column("source_quality", sa.Float(), nullable=True),
        sa.Column("raw", _JSON, nullable=False),
        sa.Column("ingested_at", _TS, nullable=False),
    )

    op.create_table(
        "rule_activations",
        sa.Column("activation_seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", _ULID, nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        sa.Column("strength", sa.String(16), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("decay_remaining", sa.Float(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_rule_activations_run_id", "rule_activations", ["run_id"])
    op.create_index("ix_rule_activations_symbol", "rule_activations", ["symbol"])
    op.create_index("ix_rule_activations_rule_id", "rule_activations", ["rule_id"])


def downgrade() -> None:
    for table in (
        "rule_activations",
        "news_items",
        "event_log",
        "call_records",
        "run_outputs",
        "run_inputs",
        "runs",
    ):
        op.drop_table(table)
