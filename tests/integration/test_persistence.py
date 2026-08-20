"""Repository + database + persistence-validation tests (M5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_state_engine.app.container import build_container
from market_state_engine.core.dtos import MacroEvent, RawSnapshot, TotalMcapSample
from market_state_engine.core.enums import EventType
from market_state_engine.persistence.models import Base, RunOutputRow, RunRow
from market_state_engine.persistence.repositories import (
    CallRecordRepository,
    EventLogRepository,
    LastGoodSnapshotRepository,
    MacroEventRepository,
    NewsRepository,
    RuleActivationRepository,
    RunRepository,
    TotalMcapSampleRepository,
)
from market_state_engine.persistence.session import Database, build_engine, create_all

from ._harness import (
    REPO,
    SequencedFake,
    build_full_container,
    fixed_clock,
    ingest_provider,
)


def _memory_db() -> Database:
    db = Database(build_engine("sqlite://"))
    db.create_all()
    return db


def test_create_all_builds_every_table() -> None:
    engine = build_engine("sqlite://")
    create_all(engine)
    expected = {
        "runs",
        "run_inputs",
        "run_outputs",
        "call_records",
        "event_log",
        "news_items",
        "rule_activations",
        "total_mcap_samples",
        "last_good_snapshots",
        "macro_events",
    }
    assert expected <= set(Base.metadata.tables)


def test_total_mcap_samples_upsert_and_read_chronologically() -> None:
    db = _memory_db()
    original = TotalMcapSample(
        symbol="TOTAL_MCAP",
        value=100.0,
        as_of="2026-08-01T00:00:00Z",
        run_id="run-1",
    )
    replacement = original.model_copy(update={"value": 105.0, "run_id": "run-2"})
    newer = TotalMcapSample(
        symbol="TOTAL_MCAP",
        value=110.0,
        as_of="2026-08-02T00:00:00Z",
        run_id="run-3",
    )
    with db.session() as session:
        repository = TotalMcapSampleRepository(session)
        repository.upsert(original)
        repository.upsert(replacement)
        repository.upsert(newer)
        samples = repository.list_recent("TOTAL_MCAP", limit=130)

    assert [(sample.as_of, sample.value) for sample in samples] == [
        ("2026-08-01T00:00:00Z", 105.0),
        ("2026-08-02T00:00:00Z", 110.0),
    ]
    assert samples[0].run_id == "run-2"


def test_last_good_snapshot_upsert_and_stale_read() -> None:
    db = _memory_db()
    live = RawSnapshot(
        source_id="coingecko",
        symbol="BTC",
        payload={"value": 100.0, "currency": "USD"},
        as_of="2026-08-01T00:00:00Z",
        is_stale=False,
        stale_reason=None,
        deviation_flags=[],
        content_hash="abc123",
    )
    newer = live.model_copy(
        update={
            "payload": {"value": 101.0, "currency": "USD"},
            "as_of": "2026-08-01T01:00:00Z",
            "content_hash": "def456",
        }
    )
    with db.session() as session:
        repository = LastGoodSnapshotRepository(session)
        repository.upsert(live)
        repository.upsert(newer)
        restored = repository.get("BTC")

    assert restored is not None
    assert restored.payload["value"] == 101.0
    assert restored.as_of == "2026-08-01T01:00:00Z"
    assert restored.is_stale is True
    assert restored.stale_reason == "last_good"
    assert restored.content_hash == "def456"


def test_marketstaterun_persisted_and_read_back() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        run = RunRepository(s).get(summary.run_id)
    assert run is not None
    assert run["run_id"] == summary.run_id
    assert len(run["assets"]) == 6


def test_callrecords_persisted() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        calls = CallRecordRepository(s).list_for_run(summary.run_id)
    assert len(calls) == 2  # sentiment + synthesis
    assert {c["llm_job"] for c in calls} == {"sentiment", "synthesis"}
    assert all(c["outcome"] == "success" for c in calls)


def test_eventlog_persists_lifecycle_events() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        events = EventLogRepository(s).list_for_run(summary.run_id)
    types = [e.event_type for e in events]
    assert "run_start" in types
    assert "provider_call" in types
    assert "run_finish" in types


def test_eventlog_records_degraded_event() -> None:
    from ._harness import build_degraded_container

    c = build_degraded_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        events = EventLogRepository(s).list_for_run(summary.run_id)
    assert "degraded" in [e.event_type for e in events]


def test_rule_activations_persisted() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        acts = RuleActivationRepository(s).list_for_run(summary.run_id)
    assert acts
    assert any(a.rule_id == "cpi_hot_risk_assets_bearish" for a in acts)


def test_run_inputs_persisted_with_hash() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    with c.database.session() as s:
        inputs = RunRepository(s).get_inputs(summary.run_id)
    assert inputs is not None
    assert inputs.snapshot_hash
    assert "price_snapshots" in inputs.raw_snapshots


def test_news_repository_upsert_idempotent() -> None:
    db = _memory_db()
    item = {
        "news_id": "n1",
        "source": "wire_reuters",
        "title": "x",
        "published_at": "2026-07-14T12:00:00Z",
        "source_quality": 0.95,
    }
    with db.session() as s:
        NewsRepository(s).upsert(item, ingested_at="2026-07-14T12:00:00Z")
    with db.session() as s:
        NewsRepository(s).upsert(item, ingested_at="2026-07-14T13:00:00Z")
        row = NewsRepository(s).get("n1")
    assert row is not None
    assert row.ingested_at == "2026-07-14T12:00:00Z"  # first write wins (idempotent)


def test_macro_event_repository_is_idempotent_and_replay_readable() -> None:
    db = _memory_db()
    event = MacroEvent(
        event_id="us_cpi_2026_08",
        event_type=EventType.US_CPI,
        scheduled_at="2026-08-20T12:30:00Z",
        consensus=0.3,
        actual=0.4,
    )
    raw = event.model_dump(mode="json")
    with db.session() as session:
        repository = MacroEventRepository(session)
        first, first_created = repository.add_if_absent(
            event,
            surprise=0.1,
            raw=raw,
            ingested_at="2026-08-20T12:31:00Z",
        )
        duplicate, duplicate_created = repository.add_if_absent(
            event.model_copy(update={"actual": 9.0}),
            surprise=8.7,
            raw={**raw, "actual": 9.0},
            ingested_at="2026-08-20T12:32:00Z",
        )
        restored = repository.get(event.event_id)
        replay_events = repository.list_events()

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.event_id == first.event_id
    assert restored is not None
    assert restored.actual == 0.4
    assert restored.surprise == 0.1
    assert restored.raw == raw
    assert restored.ingested_at == "2026-08-20T12:31:00Z"
    assert replay_events == [event]


def test_list_runs_filter_and_paginate() -> None:
    c = build_full_container()
    first = c.scheduler.run_manual()
    second = c.scheduler.run_manual()
    with c.database.session() as s:
        all_runs = RunRepository(s).list_runs(limit=10)
        events_only = RunRepository(s).list_runs(trigger_type="event", limit=10)
    assert len(all_runs) == 2
    assert len(events_only) == 2  # manual triggers are trigger_type=event
    assert [run["run_id"] for run in all_runs] == [second.run_id, first.run_id]


def test_run_sequence_is_database_backed() -> None:
    c = build_full_container()
    first = c.scheduler.run_manual()
    second = c.scheduler.run_manual()

    with c.database.session() as session:
        first_run = RunRepository(session).get(first.run_id)
        second_run = RunRepository(session).get(second.run_id)
        latest = RunRepository(session).latest()

    assert first_run is not None and first_run["run_sequence"] == 1
    assert second_run is not None and second_run["run_sequence"] == 2
    assert latest is not None and latest["run_id"] == second.run_id


def test_run_sequence_continues_after_container_restart(tmp_path: Path) -> None:
    database_path = str(tmp_path / "restart.db")
    first_container = build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=fixed_clock,
        sqlite_path=database_path,
    )
    first = first_container.scheduler.run_manual()

    restarted_container = build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=fixed_clock,
        sqlite_path=database_path,
    )
    second = restarted_container.scheduler.run_manual()

    with restarted_container.database.session() as session:
        first_run = RunRepository(session).get(first.run_id)
        second_run = RunRepository(session).get(second.run_id)
        latest = RunRepository(session).latest()

    assert first_run is not None and first_run["run_sequence"] == 1
    assert second_run is not None and second_run["run_sequence"] == 2
    assert latest is not None and latest["run_id"] == second.run_id


def test_latest_uses_completed_persistence_order_for_legacy_sequences() -> None:
    c = build_full_container()
    older = c.scheduler.run_manual()
    newer = c.scheduler.run_manual()

    with c.database.session() as session:
        older_run = session.get(RunRow, older.run_id)
        newer_run = session.get(RunRow, newer.run_id)
        older_output = session.get(RunOutputRow, older.run_id)
        newer_output = session.get(RunOutputRow, newer.run_id)
        assert older_run is not None and newer_run is not None
        assert older_output is not None and newer_output is not None
        older_run.run_sequence = 999
        newer_run.run_sequence = 1
        older_output.persisted_at = "2026-07-14T12:00:00Z"
        newer_output.persisted_at = "2026-07-14T13:00:00Z"

    with c.database.session() as session:
        latest = RunRepository(session).latest()
        listed = RunRepository(session).list_runs(limit=10)

    assert latest is not None and latest["run_id"] == newer.run_id
    assert [run["run_id"] for run in listed] == [newer.run_id, older.run_id]


def test_failed_run_does_not_replace_latest() -> None:
    c = build_full_container()
    successful = c.scheduler.run_manual()

    def failing_ingest(ctx: object) -> object:
        raise RuntimeError("ingest failed")

    c.scheduler._ingest = failing_ingest  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="ingest failed"):
        c.scheduler.run_manual()

    with c.database.session() as session:
        latest = RunRepository(session).latest()

    assert latest is not None and latest["run_id"] == successful.run_id
