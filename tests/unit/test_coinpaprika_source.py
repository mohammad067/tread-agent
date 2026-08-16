"""CoinPaprika global adapter and limited-history feature behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from market_state_engine.config.loader import load_config_bundle
from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.features.engine import FeatureEngine
from market_state_engine.ingestion.real.coinpaprika import CoinPaprikaGlobalSource
from market_state_engine.ingestion.real.provider import _mock_series_bundle
from market_state_engine.scoring.engine import ScoringEngine

REPO = Path(__file__).resolve().parents[2]


class _Client:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls = 0

    def get_global(self) -> dict[str, Any]:
        self.calls += 1
        return dict(self.response)


def _ctx() -> RunContext:
    return RunContext(
        run_id="coinpaprika-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def _response() -> dict[str, Any]:
    as_of = datetime(2026, 8, 16, 11, 55, tzinfo=timezone.utc)
    return {
        "market_cap_usd": 2_000_000_000_000,
        "volume_24h_usd": 80_000_000_000,
        "bitcoin_dominance_percentage": 55.25,
        "market_cap_change_24h": -2.5,
        "last_updated": int(as_of.timestamp()),
        "market_cap_ath_value": 4_000_000_000_000,
        "market_cap_ath_date": "2025-10-05T10:10:00Z",
    }


def test_fetch_all_uses_one_response_for_three_snapshots() -> None:
    client = _Client(_response())
    source = CoinPaprikaGlobalSource(client)
    snapshots = source.fetch_all(_ctx())

    assert client.calls == 1
    assert snapshots.dominance.payload["btc_dominance"] == 55.25
    assert snapshots.global_mcap.payload["total_market_cap_usd"] == 2_000_000_000_000
    assert snapshots.total_mcap.source_id == "coinpaprika"
    assert snapshots.total_mcap.symbol == "TOTAL_MCAP"
    assert snapshots.total_mcap.is_stale is False
    assert snapshots.total_mcap.deviation_flags == []
    assert "market_cap_ath_value" not in snapshots.total_mcap.payload


def test_total_mcap_is_not_present_in_real_provider_mock_fallbacks() -> None:
    assert "TOTAL_MCAP" not in _mock_series_bundle()


def test_total_mcap_payload_is_honest_24h_class_history() -> None:
    source = CoinPaprikaGlobalSource(_Client(_response()))
    snapshot = source.fetch_total_mcap_series(_ctx())
    changes = snapshot.payload["horizon_changes"]
    closes = snapshot.payload["closes"]

    assert isinstance(changes, dict)
    assert changes == {"6h": None, "24h": -2.5, "7d": None, "30d": None}
    assert isinstance(closes, list)
    assert len(closes) == 2
    assert snapshot.payload["highs"] == []
    assert snapshot.payload["lows"] == []
    assert snapshot.payload["volumes"] == []
    assert snapshot.payload["history_limited"] is True


def test_feature_engine_uses_real_24h_and_keeps_other_horizons_as_gaps() -> None:
    source = CoinPaprikaGlobalSource(_Client(_response()))
    snapshot = source.fetch_total_mcap_series(_ctx())
    config = load_config_bundle(REPO / "config")
    engine = FeatureEngine(config)

    features = engine.compute({}, {"TOTAL_MCAP": snapshot}, {}, [], _ctx())
    total = features.per_asset["TOTAL_MCAP"]

    assert total.changes.h6 is None
    assert total.changes.h24 == pytest.approx(-2.5)
    assert total.changes.d7 is None
    assert total.changes.d30 is None
    assert total.indicators == {}

    scored = ScoringEngine(config).score(features, previous_state=None)
    assert scored.per_asset["TOTAL_MCAP"].scores.confidence < 1.0
