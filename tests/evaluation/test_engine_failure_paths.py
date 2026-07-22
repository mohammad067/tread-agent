"""Evaluation Engine negative-path tests (M6): the checks correctly detect and report defects."""

from __future__ import annotations

from market_state_engine.evaluation.engine import (
    check_degraded_correctness,
    check_provider_correctness,
    check_replay_correctness,
)
from market_state_engine.reasoning.replay import RecordDiff, ReplayVerification


def _replay_result(*, deterministic_match: bool, full_match: bool, call_match: bool) -> object:
    class _R:
        pass

    r = _R()
    r.deterministic_match = deterministic_match  # type: ignore[attr-defined]
    r.full_deterministic_match = full_match  # type: ignore[attr-defined]
    r.call_records_match = call_match  # type: ignore[attr-defined]
    r.stored_core_fingerprint = "aaa"  # type: ignore[attr-defined]
    r.replayed_core_fingerprint = "bbb"  # type: ignore[attr-defined]
    r.call_verification = ReplayVerification(  # type: ignore[attr-defined]
        matched=call_match,
        compared=1,
        diffs=[] if call_match else [RecordDiff("[0].response_hash", "x", "y")],
    )
    return r


def test_replay_check_reports_core_divergence() -> None:
    result = _replay_result(deterministic_match=False, full_match=False, call_match=False)
    check = check_replay_correctness(result)  # type: ignore[arg-type]
    assert not check.passed
    assert any("deterministic core diverged" in f for f in check.failures)


def test_replay_check_reports_call_record_diffs_when_full_match_expected() -> None:
    # Core matched and full fingerprint matched, but call records diverged → reported.
    result = _replay_result(deterministic_match=True, full_match=True, call_match=False)
    check = check_replay_correctness(result)  # type: ignore[arg-type]
    assert not check.passed
    assert any("response_hash" in f for f in check.failures)


def test_replay_check_tolerates_call_mismatch_when_llm_leg_not_reproducible() -> None:
    # Core matched but the full (MHI) fingerprint did not (news not persisted) → call-record diffs
    # are expected and NOT a failure.
    result = _replay_result(deterministic_match=True, full_match=False, call_match=False)
    check = check_replay_correctness(result)  # type: ignore[arg-type]
    assert check.passed


def test_provider_check_reports_invalid_outcome() -> None:
    check = check_provider_correctness([{"outcome": "weird", "response": None}])
    assert not check.passed
    assert any("invalid outcome" in f for f in check.failures)


def test_provider_check_reports_nonsuccess_with_response() -> None:
    check = check_provider_correctness([{"outcome": "error", "response": {"x": 1}}])
    assert not check.passed
    assert any("non-success with non-null response" in f for f in check.failures)


def test_degraded_check_reports_summary_present() -> None:
    run = {
        "is_degraded": True,
        "assets": [{"symbol": "BTC", "scores": {"sentiment": None}, "human_summary_fa": "x"}],
        "guardrail_flags": [{"code": "degraded_run"}],
    }
    check = check_degraded_correctness(run)
    assert not check.passed
    assert any("human_summary_fa present" in f for f in check.failures)
