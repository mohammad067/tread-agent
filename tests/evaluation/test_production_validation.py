"""Production Validation tests (M6): the production-readiness verdict over source + stored data."""

from __future__ import annotations

from pathlib import Path

from market_state_engine.evaluation.engine import (
    check_contract_validity,
    check_deterministic_consistency,
    check_replay_correctness,
    check_schema_validity,
)
from market_state_engine.evaluation.replay_harness import ReplayHarness, deterministic_fingerprint
from market_state_engine.evaluation.reporting import production_validation_report
from market_state_engine.evaluation.validation import (
    ValidationReport,
    check_architecture_compatibility,
    check_provider_independence,
    check_schema_compatibility,
)
from market_state_engine.persistence.repositories import RunRepository

from ._m6_harness import REPO, fixed_clock, stored_full_run

PKG = REPO / "src" / "market_state_engine"
SCHEMAS = REPO / "schemas"


def test_architecture_compatibility_holds() -> None:
    check = check_architecture_compatibility(PKG)
    assert check.passed, check.failures


def test_schema_compatibility_holds() -> None:
    check = check_schema_compatibility(SCHEMAS)
    assert check.passed, check.failures


def test_provider_independence_holds() -> None:
    check = check_provider_independence(PKG)
    assert check.passed, check.failures


def test_full_production_validation_report() -> None:
    run_id = "PRODVAL00000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    with c.database.session() as s:
        run = RunRepository(s).get(run_id)
    assert run is not None
    replay = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    fp = deterministic_fingerprint(run)

    report = ValidationReport(
        checks=[
            check_architecture_compatibility(PKG),
            check_schema_compatibility(SCHEMAS),
            check_contract_validity(run),
            check_replay_correctness(replay),
            check_deterministic_consistency(fp, deterministic_fingerprint(run)),
            check_provider_independence(PKG),
            check_schema_validity(run, SCHEMAS),
        ]
    )
    assert report.production_ready is True
    doc = production_validation_report(report)
    assert doc["report"] == "production_validation"
    assert doc["production_ready"] is True
    names = {c["name"] for c in doc["checks"]}  # type: ignore[union-attr]
    assert "architecture_compatibility" in names
    assert "provider_independence" in names


def test_validation_report_not_ready_when_a_check_fails(tmp_path: Path) -> None:
    # A bogus schemas dir → schema compatibility fails → not production ready.
    empty = tmp_path / "schemas"
    (empty / "internal").mkdir(parents=True)
    (empty / "market_state_run.v1.0.0.json").write_text('{"type": 123}', encoding="utf-8")
    report = ValidationReport(checks=[check_schema_compatibility(empty)])
    assert report.production_ready is False
