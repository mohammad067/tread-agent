"""ADR-009 crypto spot aggregation and replay-audit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import permutations

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.evaluation.replay_harness import _rebuild_ingest
from market_state_engine.ingestion.real.aggregate import aggregate_snapshots
from market_state_engine.pipeline.orchestrator import IngestBundle
from market_state_engine.pipeline.runner import _ingest_snapshot

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
SOURCES = ("coingecko", "gate", "kifpool")


def _snapshot(
    source_id: str,
    value: object,
    *,
    symbol: str = "BTC",
    as_of: str = "2026-08-21T07:59:00Z",
    is_stale: bool = False,
    currency: str = "USD",
) -> RawSnapshot:
    payload: dict[str, object] = {
        "as_of": as_of,
        "value": value,
        "currency": currency,
        "source_quote_currency": "USDT" if source_id == "gate" else "USD",
    }
    if source_id == "gate":
        payload["source_pair"] = f"{symbol}_USDT"
    return RawSnapshot(
        source_id=source_id,
        symbol=symbol,
        payload=payload,
        as_of=as_of,
        is_stale=is_stale,
        stale_reason="source_stale" if is_stale else None,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _aggregate(
    snapshots: list[RawSnapshot], *, max_deviation_pct: float = 0.5
) -> RawSnapshot | None:
    return aggregate_snapshots(
        snapshots,
        expected_symbol="BTC",
        min_sources=2,
        configured_source_ids=SOURCES,
        max_deviation_pct=max_deviation_pct,
        now=NOW,
        staleness_threshold_minutes=15,
    )


def test_three_source_median_is_order_independent_and_audited() -> None:
    snapshots = [
        _snapshot("coingecko", 100.0),
        _snapshot("gate", 100.2),
        _snapshot("kifpool", 99.9),
    ]

    results = [_aggregate(list(order)) for order in permutations(snapshots)]

    assert all(result is not None for result in results)
    aggregates = [result for result in results if result is not None]
    assert {result.payload["value"] for result in aggregates} == {100.0}
    assert {result.payload["venue_aggregation"] for result in aggregates} == {"median_3"}
    assert {result.content_hash for result in aggregates} == {aggregates[0].content_hash}
    observations = aggregates[0].payload["source_observations"]
    assert isinstance(observations, list)
    assert [item["source_id"] for item in observations] == list(SOURCES)
    gate = observations[1]
    assert gate["source_quote_currency"] == "USDT"
    assert gate["source_pair"] == "BTC_USDT"


def test_two_agreeing_sources_publish_median_with_reduced_count_flag() -> None:
    result = _aggregate([_snapshot("coingecko", 100.0), _snapshot("gate", 100.4)])

    assert result is not None
    assert result.source_id == "crypto_median"
    assert result.payload["value"] == 100.2
    assert result.payload["venue_aggregation"] == "median_2"
    assert [flag["code"] for flag in result.deviation_flags] == ["reduced_source_count"]


def test_two_disagreeing_sources_and_one_source_are_rejected() -> None:
    assert _aggregate([_snapshot("coingecko", 100.0), _snapshot("gate", 101.0)]) is None
    assert _aggregate([_snapshot("coingecko", 100.0)]) is None
    assert _aggregate([]) is None


def test_three_source_outlier_is_flagged_but_median_remains_robust() -> None:
    result = _aggregate(
        [
            _snapshot("coingecko", 100.0),
            _snapshot("gate", 180.0),
            _snapshot("kifpool", 100.2),
        ]
    )

    assert result is not None
    assert result.payload["value"] == 100.2
    assert result.payload["venue_aggregation"] == "median_3"
    assert result.deviation_flags == [
        {
            "code": "cross_source_deviation",
            "from_source": "gate",
            "vs_source": "crypto_median",
            "deviation_pct": 79.640719,
        }
    ]


def test_stale_malformed_and_unconfigured_observations_are_removed() -> None:
    invalid = [
        _snapshot("coingecko", 0.0),
        _snapshot("gate", -1.0),
        _snapshot("kifpool", "bad"),
        _snapshot("unknown", 100.0),
    ]
    assert _aggregate(invalid) is None
    assert (
        _aggregate(
            [
                _snapshot("coingecko", 100.0),
                _snapshot("gate", 100.1, is_stale=True),
                _snapshot("kifpool", 100.2, as_of="not-a-time"),
            ]
        )
        is None
    )


def test_threshold_is_an_input_not_a_business_logic_constant() -> None:
    snapshots = [_snapshot("coingecko", 100.0), _snapshot("gate", 100.4)]

    assert _aggregate(snapshots, max_deviation_pct=0.5) is not None
    assert _aggregate(snapshots, max_deviation_pct=0.1) is None


def test_run_input_round_trip_preserves_median_flags_and_hash() -> None:
    aggregate = _aggregate(
        [
            _snapshot("coingecko", 100.0),
            _snapshot("gate", 180.0),
            _snapshot("kifpool", 100.2),
        ]
    )
    assert aggregate is not None
    ingest = IngestBundle(
        indicator_snapshots={},
        price_snapshots={"BTC": aggregate},
        global_snapshots={},
        events=[],
    )

    restored = _rebuild_ingest(_ingest_snapshot(ingest))
    replayed = restored.price_snapshots["BTC"]

    assert replayed == aggregate
    assert replayed.deviation_flags == aggregate.deviation_flags
    assert replayed.content_hash == aggregate.content_hash
    assert replayed.payload["source_observations"] == aggregate.payload["source_observations"]
