"""Evaluation Engine tests (M6): the seven correctness checks over stored runs + replays."""

from __future__ import annotations

from market_state_engine.evaluation.engine import (
    EvaluationSummary,
    check_contract_validity,
    check_degraded_correctness,
    check_deterministic_consistency,
    check_prompt_consistency,
    check_provider_correctness,
    check_replay_correctness,
    check_schema_validity,
)
from market_state_engine.evaluation.replay_harness import ReplayHarness, deterministic_fingerprint
from market_state_engine.persistence.repositories import CallRecordRepository, RunRepository

from ._m6_harness import REPO, build_degraded_container, fixed_clock, stored_full_run

SCHEMAS = REPO / "schemas"


def _calls(container: object, run_id: str) -> list[dict[str, object]]:
    with container.database.session() as s:  # type: ignore[attr-defined]
        return CallRecordRepository(s).list_for_run(run_id)


def _run(container: object, run_id: str) -> dict[str, object]:
    with container.database.session() as s:  # type: ignore[attr-defined]
        run = RunRepository(s).get(run_id)
    assert run is not None
    return run


def test_replay_correctness_check_passes() -> None:
    run_id = "EVALRPLY0000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    assert check_replay_correctness(result).passed


def test_provider_correctness_check() -> None:
    run_id = "EVALPROV0000000000000000AB"
    c = stored_full_run(run_id)
    check = check_provider_correctness(_calls(c, run_id))
    assert check.passed


def test_provider_correctness_detects_bad_shape() -> None:
    # success outcome with null response is incoherent.
    bad = [{"outcome": "success", "response": None}]
    assert not check_provider_correctness(bad).passed


def test_deterministic_consistency_check() -> None:
    run_id = "EVALDET00000000000000000AB"
    run = _run(stored_full_run(run_id), run_id)
    fp1 = deterministic_fingerprint(run)
    fp2 = deterministic_fingerprint(run)
    assert check_deterministic_consistency(fp1, fp2).passed
    assert not check_deterministic_consistency("a", "b").passed


def test_schema_validity_check() -> None:
    run_id = "EVALSCHM0000000000000000AB"
    run = _run(stored_full_run(run_id), run_id)
    assert check_schema_validity(run, SCHEMAS).passed


def test_contract_validity_check() -> None:
    run_id = "EVALCTRT0000000000000000AB"
    run = _run(stored_full_run(run_id), run_id)
    assert check_contract_validity(run).passed
    assert not check_contract_validity({"run_id": "x"}).passed


def test_degraded_correctness_check() -> None:
    run_id = "EVALDEGR0000000000000000AB"
    c = build_degraded_container()
    c.scheduler.run_manual(run_id=run_id)
    run = _run(c, run_id)
    assert check_degraded_correctness(run).passed  # honest absence + flag


def test_degraded_correctness_flags_dishonesty() -> None:
    dishonest = {
        "is_degraded": True,
        "assets": [{"symbol": "BTC", "scores": {"sentiment": 0.1}}],
        "guardrail_flags": [],
    }
    assert not check_degraded_correctness(dishonest).passed


def test_prompt_consistency_check() -> None:
    run_id = "EVALPRMT0000000000000000AB"
    c = stored_full_run(run_id)
    assert check_prompt_consistency(_calls(c, run_id)).passed


def test_prompt_consistency_detects_hash_mismatch() -> None:
    bad = [
        {"rendered_prompt": "same", "prompt_hash": "h1"},
        {"rendered_prompt": "same", "prompt_hash": "h2"},
    ]
    assert not check_prompt_consistency(bad).passed


def test_evaluation_summary_aggregates() -> None:
    run_id = "EVALSUMM0000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    run = _run(c, run_id)
    calls = _calls(c, run_id)
    summary = EvaluationSummary(
        checks=[
            check_replay_correctness(result),
            check_provider_correctness(calls),
            check_schema_validity(run, SCHEMAS),
            check_contract_validity(run),
            check_degraded_correctness(run),
            check_prompt_consistency(calls),
        ]
    )
    assert summary.passed
    assert summary.pass_count == 6
