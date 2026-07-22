"""ReplayHarness tests (M6): load stored snapshots + call records, replay offline, verify."""

from __future__ import annotations

import pytest

from market_state_engine.evaluation.replay_harness import ReplayHarness

from ._m6_harness import REPO, fixed_clock, stored_full_run


def test_replay_reproduces_deterministic_core() -> None:
    run_id = "RPLYCORE0000000000000000AB"
    c = stored_full_run(run_id)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    assert result.deterministic_match is True  # frozen guarantee: core reproduces byte-identically
    assert result.ok is True


def test_replay_full_leg_reproduces_when_inputs_fully_persisted() -> None:
    # With no news, the sentiment prompt is fully reconstructable → the LLM leg replays too, so the
    # full deterministic fingerprint AND the call records reproduce.
    run_id = "RPLYFULL0000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    assert result.deterministic_match is True
    assert result.full_deterministic_match is True
    assert result.call_records_match is True
    assert result.reproduced_is_degraded is False


def test_replay_uses_only_replay_provider_no_live_call() -> None:
    # The replay container is wired with ReplayProviders only; a live provider would raise. Success
    # proves no live provider was contacted.
    run_id = "RPLYNOLI0000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    result = ReplayHarness(REPO, fixed_clock).run(c.database, run_id)
    assert result.ok is True


def test_replay_unknown_run_raises() -> None:
    c = stored_full_run("RPLYKNOWN000000000000000AB")
    with pytest.raises(ValueError, match="no stored inputs"):
        ReplayHarness(REPO, fixed_clock).load(c.database, "DOES_NOT_EXIST")


def test_replay_is_deterministic_across_two_runs() -> None:
    run_id = "RPLYTWICE000000000000000AB"
    c = stored_full_run(run_id, no_news=True)
    harness = ReplayHarness(REPO, fixed_clock)
    r1 = harness.run(c.database, run_id)
    r2 = harness.run(c.database, run_id)
    assert r1.stored_core_fingerprint == r2.stored_core_fingerprint
    assert r1.replayed_core_fingerprint == r2.replayed_core_fingerprint
