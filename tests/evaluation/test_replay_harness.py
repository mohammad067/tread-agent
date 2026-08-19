"""ReplayHarness tests (M6): load stored snapshots + call records, replay offline, verify."""

from __future__ import annotations

import pytest

from market_state_engine.evaluation.replay_harness import ReplayHarness
from market_state_engine.ingestion.real import news_feeds
from market_state_engine.persistence.repositories import RunRepository

from ._m6_harness import REPO, fixed_clock, stored_full_run, stored_stale_news_run


def test_replay_with_news_restores_inputs_and_prompt_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "RPLYCORE0000000000000000AB"
    c = stored_full_run(run_id)
    harness = ReplayHarness(REPO, fixed_clock)

    with c.database.session() as session:
        stored_inputs = RunRepository(session).get_inputs(run_id)
    assert stored_inputs is not None
    persisted_news = stored_inputs.raw_snapshots["news_items"]
    assert isinstance(persisted_news, list)
    assert [item["news_id"] for item in persisted_news] == ["n1"]

    loaded = harness.load(c.database, run_id)

    assert [item.news_id for item in loaded.ingest.news_items] == ["n1"]
    assert loaded.ingest.news_items[0].body == "Bitcoin falls after hot CPI"

    sentiment_call = next(
        record for record in loaded.call_records if record.llm_job.value == "sentiment"
    )
    assert '"evidence_text": "Bitcoin falls after hot CPI"' in sentiment_call.rendered_prompt

    def fail_live_fetch(_url: str) -> bytes:
        raise AssertionError("live RSS fetch attempted during replay")

    monkeypatch.setattr(news_feeds, "_fetch", fail_live_fetch)
    result = harness.replay(loaded)
    assert result.deterministic_match is True
    assert result.full_deterministic_match is True
    # verify_replay includes prompt_hash among its replay-critical fields.
    assert result.call_records_match is True
    assert result.call_verification.compared == 2
    assert result.call_verification.diffs == []
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


def test_37_hour_news_is_ineligible_in_live_and_replay() -> None:
    run_id = "RPLYSTALE000000000000000AB"
    c = stored_stale_news_run(run_id)
    harness = ReplayHarness(REPO, fixed_clock)
    loaded = harness.load(c.database, run_id)

    assert [item.news_id for item in loaded.ingest.news_items] == ["stale-news"]
    assert [record.llm_job.value for record in loaded.call_records] == ["synthesis"]

    result = harness.replay(loaded)

    assert result.deterministic_match is True
    assert result.full_deterministic_match is True
    assert result.call_records_match is True
    assert result.call_verification.compared == 1
    assert result.call_verification.diffs == []
    assert result.reproduced_is_degraded is False
