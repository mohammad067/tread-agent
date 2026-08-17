"""SQLAlchemy ORM models — the physical realization of database.md §4 (all tables).

Dialect-neutral (ADR-006): JSON columns use a portable variant (``JSON`` on SQLite, ``JSONB`` on
Postgres); ULIDs are ``CHAR(26)``; timestamps are timezone-aware ISO strings stored as text (the
contract already carries ISO-8601 strings, so no dialect datetime coupling). No dialect-only SQL.

Append-only discipline (``run_inputs``, ``run_outputs``, ``call_records``, ``event_log``) is
enforced at the repository layer, not here — these tables are simply never issued an UPDATE.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeEngine

# Portable JSON: JSONB on Postgres, JSON elsewhere (SQLite). One type, both dialects (§B.2).
PortableJSON: TypeEngine[object] = JSON().with_variant(JSONB(), "postgresql")

_ULID = String(26)
_VERSION = String(64)
_TS = String(32)  # ISO-8601 timezone-aware string (contract-native)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    """``runs`` — run identity & versions (database.md §4.1). Only status/is_degraded may update."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(_ULID, primary_key=True)
    run_sequence: Mapped[int] = mapped_column(Integer, index=True)
    trigger_type: Mapped[str] = mapped_column(String(16), index=True)
    trigger_detail: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    generated_at: Mapped[str] = mapped_column(_TS, index=True)
    schema_version: Mapped[str] = mapped_column(_VERSION)
    pipeline_version: Mapped[str] = mapped_column(_VERSION)
    provider_version: Mapped[str | None] = mapped_column(_VERSION, nullable=True)
    model_version: Mapped[str | None] = mapped_column(_VERSION, nullable=True)
    prompt_sentiment_version: Mapped[str] = mapped_column(_VERSION)
    prompt_synthesis_version: Mapped[str] = mapped_column(_VERSION)
    rulebook_version: Mapped[str] = mapped_column(_VERSION)
    mhi_weights_version: Mapped[str] = mapped_column(_VERSION)
    pricing_version: Mapped[str | None] = mapped_column(_VERSION, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    is_degraded: Mapped[bool] = mapped_column(Boolean, default=False)


class RunInputRow(Base):
    """``run_inputs`` — immutable input snapshot 1:1 (database.md §4.2). Append-only."""

    __tablename__ = "run_inputs"

    run_id: Mapped[str] = mapped_column(_ULID, primary_key=True)
    raw_snapshots: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    data_gaps: Mapped[list[object]] = mapped_column(PortableJSON)
    deviation_flags: Mapped[list[object]] = mapped_column(PortableJSON)
    ingested_at: Mapped[str] = mapped_column(_TS)


class RunOutputRow(Base):
    """``run_outputs`` — immutable output 1:1 (database.md §4.3). Append-only."""

    __tablename__ = "run_outputs"

    run_id: Mapped[str] = mapped_column(_ULID, primary_key=True)
    market_state_run: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    guardrail_flags: Mapped[list[object]] = mapped_column(PortableJSON)
    output_hash: Mapped[str] = mapped_column(String(64))
    persisted_at: Mapped[str] = mapped_column(_TS)


class CallRecordRow(Base):
    """``call_records`` — per-LLM-attempt replay/cost/metrics unit (database §4.5). Append-only."""

    __tablename__ = "call_records"

    call_id: Mapped[str] = mapped_column(_ULID, primary_key=True)
    run_id: Mapped[str] = mapped_column(_ULID, index=True)
    llm_job: Mapped[str] = mapped_column(String(16))
    attempt_index: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_id: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(_VERSION)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    rendered_prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    retries: Mapped[int] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[str] = mapped_column(_TS, index=True)


class EventLogRow(Base):
    """``event_log`` — append-only execution-event stream (pipelines.md §7).

    Complements the immutable snapshot/output/call-record tables with a chronological trace of
    lifecycle events (start/finish/failure/degraded/provider/replay/scheduler) for observability and
    audit. Payload is a free-form JSON object; ``run_id`` is nullable for scheduler-level events.
    """

    __tablename__ = "event_log"

    event_seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(_ULID, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    created_at: Mapped[str] = mapped_column(_TS)


class NewsItemRow(Base):
    """``news_items`` — ingested news feed records (database.md §4.8)."""

    __tablename__ = "news_items"

    news_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(128))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str] = mapped_column(_TS)
    source_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    ingested_at: Mapped[str] = mapped_column(_TS)


class RuleActivationRow(Base):
    """Persisted RuleActivation per (run, asset) — the activated rules a run produced.

    A queryable projection of the rule activations embedded in ``run_outputs.market_state_run``,
    kept append-only for rule-performance evaluation without re-parsing whole output documents.
    """

    __tablename__ = "rule_activations"

    activation_seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(_ULID, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rule_id: Mapped[str] = mapped_column(String(128), index=True)
    strength: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[str] = mapped_column(String(16))
    decay_remaining: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(_TS)


class TotalMcapSampleRow(Base):
    """Deduplicated TOTAL_MCAP observations keyed by symbol and source timestamp."""

    __tablename__ = "total_mcap_samples"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[str] = mapped_column(_TS, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    run_id: Mapped[str | None] = mapped_column(_ULID, nullable=True)


class LastGoodSnapshotRow(Base):
    """Latest successful real-ingest snapshot for one market symbol."""

    __tablename__ = "last_good_snapshots"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(PortableJSON)
    as_of: Mapped[str] = mapped_column(_TS)
    deviation_flags: Mapped[list[object]] = mapped_column(PortableJSON)
    content_hash: Mapped[str] = mapped_column(String(64))
