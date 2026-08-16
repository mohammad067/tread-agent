"""CoinMarketCap keyless global adapter and limited-history behavior."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from market_state_engine.config.loader import load_config_bundle
from market_state_engine.core.dtos import TotalMcapSample
from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.features.engine import FeatureEngine
from market_state_engine.ingestion.real.coinmarketcap import (
    CoinMarketCapGlobalSource,
    enrich_total_mcap_history,
)
from market_state_engine.ingestion.real.provider import _mock_series_bundle

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "coinmarketcap_global_latest.sanitized.json"


class _Client:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls = 0

    def get_latest(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.response))  # isolated response per call


def _ctx() -> RunContext:
    return RunContext(
        run_id="coinmarketcap-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 16, 12, 5, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def _fixture() -> dict[str, Any]:
    value: object = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fixture_mapping_builds_three_consistent_snapshots() -> None:
    client = _Client(_fixture())
    snapshots = CoinMarketCapGlobalSource(client).fetch_all(_ctx())

    assert client.calls == 1
    assert snapshots.total_mcap.source_id == "coinmarketcap"
    assert snapshots.total_mcap.symbol == "TOTAL_MCAP"
    assert snapshots.total_mcap.payload["value"] == 2264417762062.0
    assert snapshots.total_mcap.payload["horizon_changes"] == {
        "6h": None,
        "24h": -0.02,
        "7d": None,
        "30d": None,
    }
    assert "closes" not in snapshots.total_mcap.payload
    assert snapshots.dominance.payload["btc_dominance"] == 55.77
    assert snapshots.global_mcap.payload["total_market_cap_usd"] == 2264417762062.0
    assert snapshots.total_mcap.as_of == "2026-08-16T12:00:00Z"
    assert snapshots.total_mcap.is_stale is False


def test_24h_falls_back_to_today_vs_yesterday() -> None:
    response = _fixture()
    usd = response["data"]["quote"]["USD"]
    del usd["total_market_cap_yesterday_percentage_change"]
    snapshots = CoinMarketCapGlobalSource(_Client(response)).fetch_all(_ctx())
    changes = snapshots.total_mcap.payload["horizon_changes"]

    assert isinstance(changes, dict)
    expected = (2264417762062.0 - 2264870736209.2417) / 2264870736209.2417 * 100
    assert changes["24h"] == pytest.approx(expected)


def test_missing_required_market_cap_raises_clear_error() -> None:
    response = _fixture()
    del response["data"]["quote"]["USD"]["total_market_cap"]

    with pytest.raises(RuntimeError, match=r"CoinMarketCap.*total_market_cap"):
        CoinMarketCapGlobalSource(_Client(response)).fetch_all(_ctx())


def test_feature_engine_uses_explicit_24h_without_fabricating_other_horizons() -> None:
    snapshot = CoinMarketCapGlobalSource(_Client(_fixture())).fetch_total_mcap_series(_ctx())
    engine = FeatureEngine(load_config_bundle(REPO / "config"))
    features = engine.compute({}, {"TOTAL_MCAP": snapshot}, {}, [], _ctx())
    total = features.per_asset["TOTAL_MCAP"]

    assert total.changes.h6 is None
    assert total.changes.h24 == pytest.approx(-0.02)
    assert total.changes.d7 is None
    assert total.changes.d30 is None
    assert total.indicators == {}


def test_total_mcap_has_no_real_provider_mock_fallback() -> None:
    assert "TOTAL_MCAP" not in _mock_series_bundle()


def test_history_enrichment_builds_real_7d_and_30d_changes() -> None:
    snapshot = CoinMarketCapGlobalSource(_Client(_fixture())).fetch_total_mcap_series(_ctx())
    samples = [
        TotalMcapSample(
            symbol="TOTAL_MCAP",
            value=1_800_000_000_000.0,
            as_of="2026-07-17T12:00:00Z",
        ),
        TotalMcapSample(
            symbol="TOTAL_MCAP",
            value=2_100_000_000_000.0,
            as_of="2026-08-09T12:00:00Z",
        ),
        TotalMcapSample(
            symbol="TOTAL_MCAP",
            value=2264417762062.0,
            as_of="2026-08-16T12:00:00Z",
        ),
    ]

    enriched = enrich_total_mcap_history(snapshot, samples)
    changes = enriched.payload["horizon_changes"]
    assert isinstance(changes, dict)
    assert changes["6h"] is None
    assert changes["7d"] == pytest.approx((2264417762062.0 / 2_100_000_000_000.0 - 1) * 100)
    assert changes["30d"] == pytest.approx((2264417762062.0 / 1_800_000_000_000.0 - 1) * 100)
    assert enriched.payload["closes"] == [
        1_800_000_000_000.0,
        2_100_000_000_000.0,
        2264417762062.0,
    ]
    assert enriched.payload["data_gaps"] == ["missing_6h_change"]


def test_history_enrichment_keeps_missing_horizons_as_gaps() -> None:
    snapshot = CoinMarketCapGlobalSource(_Client(_fixture())).fetch_total_mcap_series(_ctx())
    samples = [
        TotalMcapSample(
            symbol="TOTAL_MCAP",
            value=2264417762062.0,
            as_of="2026-08-16T12:00:00Z",
        )
    ]

    enriched = enrich_total_mcap_history(snapshot, samples)
    changes = enriched.payload["horizon_changes"]
    assert isinstance(changes, dict)
    assert changes["7d"] is None
    assert changes["30d"] is None
    assert enriched.payload["data_gaps"] == [
        "missing_6h_change",
        "missing_7d_change",
        "missing_30d_change",
    ]
