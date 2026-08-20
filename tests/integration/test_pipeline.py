"""Pipeline integration + degraded-pipeline tests (M5): full 10-stage flow through the port."""

from __future__ import annotations

import pytest

from market_state_engine.app.container import build_container
from market_state_engine.core.dtos import NewsItem
from market_state_engine.core.enums import RegimeState
from market_state_engine.persistence.repositories import CallRecordRepository, RunRepository
from market_state_engine.pipeline.orchestrator import IngestBundle
from market_state_engine.pipeline.scheduler import ExecutionMode, OverlapError

from ._harness import (
    REPO,
    SYMBOLS,
    SequencedFake,
    build_degraded_container,
    build_full_container,
    fixed_clock,
    ingest_provider,
)


def _container_with_news(news_items: list[NewsItem]):  # type: ignore[no-untyped-def]
    def provider(ctx: object) -> IngestBundle:
        base = ingest_provider(ctx)
        return IngestBundle(
            indicator_snapshots=base.indicator_snapshots,
            price_snapshots=base.price_snapshots,
            global_snapshots=base.global_snapshots,
            events=base.events,
            news_items=news_items,
        )

    return build_container(
        REPO,
        env="dev",
        ingest_provider=provider,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )


def test_full_pipeline_produces_non_degraded_run() -> None:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    assert summary.status == "published"
    assert summary.is_degraded is False
    with c.database.session() as s:
        from market_state_engine.persistence.repositories import RunRepository

        run = RunRepository(s).get(summary.run_id)
    assert run is not None
    assert {a["symbol"] for a in run["assets"]} == set(SYMBOLS)  # multi-asset
    btc = next(a for a in run["assets"] if a["symbol"] == "BTC")
    assert btc["scores"]["sentiment"] == -0.2  # LLM sentiment applied
    assert "human_summary_fa" in btc  # synthesis composed in


def test_degraded_pipeline_still_succeeds_when_all_providers_fail() -> None:
    c = build_degraded_container()
    summary = c.scheduler.run_manual()
    assert summary.published is True  # never aborts (ADR-011)
    assert summary.is_degraded is True
    with c.database.session() as s:
        from market_state_engine.persistence.repositories import RunRepository

        run = RunRepository(s).get(summary.run_id)
    assert run is not None
    assert run["is_degraded"] is True
    for asset in run["assets"]:
        assert asset["scores"]["sentiment"] is None  # honest absence
        assert "human_summary_fa" not in asset
    assert "degraded_run" in {f["code"] for f in run["guardrail_flags"]}


def test_pipeline_publishes_honest_unavailable_prices_without_ingest_snapshots() -> None:
    def unavailable_ingest(ctx: object) -> IngestBundle:
        return IngestBundle({}, {}, {}, [], [])

    c = build_container(
        REPO,
        env="dev",
        ingest_provider=unavailable_ingest,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )

    summary = c.scheduler.run_manual()
    with c.database.session() as session:
        run = RunRepository(session).get(summary.run_id)

    assert summary.published is True
    assert run is not None
    assert {asset["symbol"] for asset in run["assets"]} == set(SYMBOLS)
    assert all(asset["price"]["is_stale"] is True for asset in run["assets"])
    assert all(
        asset["price"]["stale_reason"] == "price_unavailable" for asset in run["assets"]
    )


def test_empty_digest_skips_sentiment_but_synthesis_remains_healthy() -> None:
    c = _container_with_news([])
    summary = c.scheduler.run_manual()
    with c.database.session() as session:
        run = RunRepository(session).get(summary.run_id)
        calls = CallRecordRepository(session).list_for_run(summary.run_id)

    assert run is not None
    assert summary.is_degraded is False
    assert [call["llm_job"] for call in calls] == ["synthesis"]
    assert "degraded_run" not in {flag["code"] for flag in run["guardrail_flags"]}
    assert all(asset["scores"]["sentiment"] is None for asset in run["assets"])
    assert all("human_summary_fa" in asset for asset in run["assets"])


def test_sentiment_is_limited_to_assets_with_digest_evidence() -> None:
    news = [
        NewsItem(
            news_id="btc-only",
            title="Bitcoin market update",
            source="wire_reuters",
            published_at="2026-07-14T12:35:00Z",
            asset_tags=["BTC"],
        )
    ]
    c = _container_with_news(news)
    summary = c.scheduler.run_manual()
    with c.database.session() as session:
        run = RunRepository(session).get(summary.run_id)
        calls = CallRecordRepository(session).list_for_run(summary.run_id)

    assert run is not None
    sentiments = {
        asset["symbol"]: asset["scores"]["sentiment"] for asset in run["assets"]
    }
    assert sentiments["BTC"] == -0.2
    assert all(sentiments[symbol] is None for symbol in SYMBOLS if symbol != "BTC")
    sentiment_call = next(call for call in calls if call["llm_job"] == "sentiment")
    synthesis_call = next(call for call in calls if call["llm_job"] == "synthesis")
    assert "دارایی‌های هدف: BTC" in sentiment_call["rendered_prompt"]
    assert '"per_asset_sentiment": {\n    "BTC": -0.2' in synthesis_call["rendered_prompt"]


def test_deterministic_fields_identical_across_full_and_degraded() -> None:
    # Deterministic fields (trend/risk/regime) do not depend on the LLM (ADR-011 DR-4).
    from market_state_engine.persistence.repositories import RunRepository

    fc = build_full_container()
    fs = fc.scheduler.run_manual()
    with fc.database.session() as s:
        full_run = RunRepository(s).get(fs.run_id)

    dc = build_degraded_container()
    ds = dc.scheduler.run_manual()
    with dc.database.session() as s:
        deg_run = RunRepository(s).get(ds.run_id)

    assert full_run is not None and deg_run is not None
    fbtc = next(a for a in full_run["assets"] if a["symbol"] == "BTC")
    dbtc = next(a for a in deg_run["assets"] if a["symbol"] == "BTC")
    assert fbtc["scores"]["trend"] == dbtc["scores"]["trend"]
    assert fbtc["scores"]["risk"] == dbtc["scores"]["risk"]
    assert full_run["regime"]["state"] == deg_run["regime"]["state"]


def test_overlapping_runs_are_prevented() -> None:
    # A second trigger issued while the first is still executing (from inside its ingest hook) is
    # refused with OverlapError — the single-node overlap guard (pipelines.md §1).
    c = build_full_container()
    reentered: list[bool] = []
    from ._harness import ingest_provider

    def _reentrant_ingest(ctx: object) -> object:
        try:
            c.scheduler.trigger(ExecutionMode.SCHEDULED)
        except OverlapError:
            reentered.append(True)
        return ingest_provider(ctx)

    c.scheduler._ingest = _reentrant_ingest  # type: ignore[attr-defined]
    c.scheduler.run_manual()
    assert reentered == [True]


def test_idempotent_retrigger_is_noop() -> None:
    c = build_full_container()
    first = c.scheduler.run_manual(run_id="01J8ZK3W9P4Q5R6S7T8U9V0W1X")
    second = c.scheduler.run_manual(run_id="01J8ZK3W9P4Q5R6S7T8U9V0W1X")
    assert first.idempotent_noop is False
    assert second.idempotent_noop is True


@pytest.mark.parametrize("mode", [ExecutionMode.SCHEDULED, ExecutionMode.MANUAL])
def test_trigger_modes(mode: ExecutionMode) -> None:
    c = build_full_container()
    summary = c.scheduler.trigger(mode)
    assert summary.status in {"published", "degraded"}
