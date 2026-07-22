"""Metrics + Reporting tests (M6)."""

from __future__ import annotations

from market_state_engine.evaluation.engine import EvaluationSummary, check_contract_validity
from market_state_engine.evaluation.metrics import (
    collect_call_metrics,
    collect_replay_rate,
    collect_run_rates,
)
from market_state_engine.evaluation.replay_harness import ReplayHarness
from market_state_engine.evaluation.reporting import (
    degradation_report,
    evaluation_report,
    provider_report,
    replay_report,
)
from market_state_engine.persistence.repositories import CallRecordRepository, RunRepository

from ._m6_harness import REPO, build_degraded_container, fixed_clock, stored_full_run


def _calls(container: object, run_id: str) -> list[dict[str, object]]:
    with container.database.session() as s:  # type: ignore[attr-defined]
        return CallRecordRepository(s).list_for_run(run_id)


# --- metrics -------------------------------------------------------------------------
def test_call_metrics_tokens_cost_latency() -> None:
    run_id = "METRCALL0000000000000000AB"
    c = stored_full_run(run_id)
    m = collect_call_metrics(_calls(c, run_id))
    assert m.total_calls == 2
    assert m.success_rate == 1.0
    assert m.total_input_tokens > 0
    assert m.total_estimated_cost > 0
    assert "openai" in m.per_provider
    assert m.per_provider["openai"].success_rate == 1.0


def test_run_rate_metrics_degraded() -> None:
    run_id = "METRRATE0000000000000000AB"
    c = build_degraded_container()
    c.scheduler.run_manual(run_id=run_id)
    with c.database.session() as s:
        run = RunRepository(s).get(run_id)
    rates = collect_run_rates([run] if run else [])
    assert rates.total_runs == 1
    assert rates.degraded_runs == 1
    assert rates.degraded_rate == 1.0


def test_replay_rate_metrics() -> None:
    rate = collect_replay_rate([True, True, False, True])
    assert rate.attempts == 4
    assert rate.successes == 3
    assert rate.replay_success_rate == 0.75


def test_call_metrics_empty() -> None:
    m = collect_call_metrics([])
    assert m.total_calls == 0
    assert m.success_rate == 0.0


# --- reporting -----------------------------------------------------------------------
def test_replay_report_shape() -> None:
    run_id = "REPTRPLY0000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    report = replay_report([result])
    assert report["report"] == "replay"
    assert report["attempts"] == 1
    assert report["replay_success_rate"] == 1.0
    assert report["runs"][0]["deterministic_match"] is True


def test_provider_report_shape() -> None:
    run_id = "REPTPROV0000000000000000AB"
    c = stored_full_run(run_id)
    report = provider_report(collect_call_metrics(_calls(c, run_id)))
    assert report["report"] == "provider"
    assert report["total_calls"] == 2
    assert "openai" in report["per_provider"]


def test_evaluation_report_shape() -> None:
    run_id = "REPTEVAL0000000000000000AB"
    c = stored_full_run(run_id)
    with c.database.session() as s:
        run = RunRepository(s).get(run_id)
    assert run is not None
    summary = EvaluationSummary(checks=[check_contract_validity(run)])
    report = evaluation_report(summary)
    assert report["report"] == "evaluation"
    assert report["passed"] is True
    assert report["total_checks"] == 1


def test_degradation_report_shape() -> None:
    rates = collect_run_rates([{"is_degraded": True}, {"is_degraded": False}])
    report = degradation_report(rates, honesty_ok=True)
    assert report["report"] == "degradation"
    assert report["degraded_runs"] == 1
    assert report["honest_absence_verified"] is True
