"""Repository + database + persistence-validation tests (M5)."""

from __future__ import annotations

from market_state_engine.persistence.models import Base
from market_state_engine.persistence.repositories import (
    CallRecordRepository,
    EventLogRepository,
    NewsRepository,
    RuleActivationRepository,
    RunRepository,
)
from market_state_engine.persistence.session import Database, build_engine, create_all

from ._harness import build_full_container


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
    }
    assert expected <= set(Base.metadata.tables)


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


def test_list_runs_filter_and_paginate() -> None:
    c = build_full_container()
    c.scheduler.run_manual()
    c.scheduler.run_manual()
    with c.database.session() as s:
        all_runs = RunRepository(s).list_runs(limit=10)
        events_only = RunRepository(s).list_runs(trigger_type="event", limit=10)
    assert len(all_runs) == 2
    assert len(events_only) == 2  # manual triggers are trigger_type=event
