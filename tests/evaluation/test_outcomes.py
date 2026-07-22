"""OutcomeRecorder tests (M6): records every execution-outcome kind to the append-only event_log."""

from __future__ import annotations

from market_state_engine.evaluation.outcomes import OutcomeKind, OutcomeRecorder
from market_state_engine.persistence.session import Database, build_engine

from ._m6_harness import fixed_clock


def _db() -> Database:
    db = Database(build_engine("sqlite://"))
    db.create_all()
    return db


def test_records_all_outcome_kinds() -> None:
    db = _db()
    rec = OutcomeRecorder(db, fixed_clock)
    rec.record_success("run1", {"detail": "ok"})
    rec.record_degraded("run1")
    rec.record_replay("run1", {"deterministic_match": True})
    rec.record_provider("run1", {"provider": "openai"})
    rec.record_evaluation({"checks": 6})
    rec.record_validation({"production_ready": True})
    outcomes = rec.outcomes_for_run("run1")
    kinds = {o["kind"] for o in outcomes}
    assert kinds == {
        OutcomeKind.SUCCESS.value,
        OutcomeKind.DEGRADED.value,
        OutcomeKind.REPLAY.value,
        OutcomeKind.PROVIDER.value,
    }  # evaluation/validation have no run_id


def test_outcome_payload_carries_detail() -> None:
    db = _db()
    rec = OutcomeRecorder(db, fixed_clock)
    rec.record_replay("runX", {"deterministic_match": True, "call_records_match": False})
    [outcome] = rec.outcomes_for_run("runX")
    assert outcome["kind"] == "replay"
    assert outcome["deterministic_match"] is True
    assert outcome["call_records_match"] is False


def test_outcomes_are_append_only() -> None:
    db = _db()
    rec = OutcomeRecorder(db, fixed_clock)
    rec.record_success("r")
    rec.record_success("r")
    assert len(rec.outcomes_for_run("r")) == 2  # both retained, none overwritten


def test_run_scoped_read_isolates_runs() -> None:
    db = _db()
    rec = OutcomeRecorder(db, fixed_clock)
    rec.record_success("a")
    rec.record_success("b")
    assert len(rec.outcomes_for_run("a")) == 1
    assert len(rec.outcomes_for_run("b")) == 1
