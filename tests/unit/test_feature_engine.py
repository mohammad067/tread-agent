"""FeatureEngine integration: mock ingestors -> FeatureEngine -> schema-valid FeatureSet.

Exercises the deterministic input pipeline end-to-end with no network, no clock, no DB.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from market_state_engine.config.loader import load_config_bundle
from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import EventType, TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.features.engine import FeatureEngine
from market_state_engine.ingestion.mocks.mock_sources import (
    MockDominanceSource,
    MockFearGreedSource,
    MockIndicatorInputSource,
    MockTotalMcapSource,
)

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "config"
FEATURE_SET_SCHEMA = REPO / "schemas" / "internal" / "feature_set.v1.json"

ALL_SYMBOLS = ["BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"]


def _series(base: float, n: int = 130, slope: float = 0.5) -> dict[str, Any]:
    closes = [base + slope * i + 2.0 * math.sin(i / 3.0) for i in range(n)]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    volumes = [1000.0 + 10.0 * i for i in range(n)]
    return {
        "as_of": "2026-07-14T12:45:00Z",
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(
        run_id="01J8ZK3W9P4Q5R6S7T8U9V0W1X",
        run_sequence=1842,
        trigger_type=TriggerType.EVENT,
        now=datetime(2026, 7, 14, 12, 47, 3, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


@pytest.fixture()
def engine() -> FeatureEngine:
    return FeatureEngine(load_config_bundle(CONFIG_DIR))


def _indicator_snapshots(ctx: RunContext) -> dict[str, Any]:
    src = MockIndicatorInputSource({s: _series(100.0 + i * 10) for i, s in enumerate(ALL_SYMBOLS)})
    return {s: src.fetch_series(s, ctx) for s in ALL_SYMBOLS}


def test_feature_set_validates_against_schema(engine: FeatureEngine, ctx: RunContext) -> None:
    ind_snaps = _indicator_snapshots(ctx)
    global_snaps = {
        "fear_greed": MockFearGreedSource(24, "2026-07-14T12:45:00Z").fetch(ctx),
        "dominance": MockDominanceSource(56.8, "2026-07-14T12:45:00Z").fetch(ctx),
        "total_mcap": MockTotalMcapSource(3.91e12, "2026-07-14T12:45:00Z").fetch(ctx),
    }
    events = [
        MacroEvent(
            event_id="us_cpi_2026_07",
            event_type=EventType.US_CPI,
            scheduled_at="2026-07-14T12:30:00Z",
            consensus=0.3,
            actual=0.4,
        )
    ]
    fs = engine.compute({}, ind_snaps, global_snaps, events, ctx)
    doc = json.loads(json.dumps(fs.to_contract_dict()))  # ensure JSON-serializable

    schema = json.loads(FEATURE_SET_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)

    assert set(fs.per_asset) == set(ALL_SYMBOLS)
    assert fs.event_features[0].surprise == pytest.approx(0.1)
    assert fs.config_versions["mhi_weights"] == "1.1.0"


def test_index_asset_has_reduced_indicators(engine: FeatureEngine, ctx: RunContext) -> None:
    ind_snaps = _indicator_snapshots(ctx)
    fs = engine.compute({}, ind_snaps, {}, [], ctx)
    total = fs.per_asset["TOTAL_MCAP"]
    assert total.indicators is not None
    assert "rsi_14" not in total.indicators
    assert "macd_state" not in total.indicators


def test_full_asset_has_full_indicators(engine: FeatureEngine, ctx: RunContext) -> None:
    ind_snaps = _indicator_snapshots(ctx)
    fs = engine.compute({}, ind_snaps, {}, [], ctx)
    btc = fs.per_asset["BTC"]
    assert btc.indicators is not None
    assert "rsi_14" in btc.indicators
    assert "macd_state" in btc.indicators
    assert "ema_20_50" in btc.indicators


def test_determinism_two_runs_identical(engine: FeatureEngine, ctx: RunContext) -> None:
    ind_snaps = _indicator_snapshots(ctx)
    fs1 = engine.compute({}, ind_snaps, {}, [], ctx).to_contract_dict()
    fs2 = engine.compute({}, ind_snaps, {}, [], ctx).to_contract_dict()
    assert json.dumps(fs1, sort_keys=True) == json.dumps(fs2, sort_keys=True)


def test_missing_indicator_snapshot_degrades_to_gaps(
    engine: FeatureEngine, ctx: RunContext
) -> None:
    # No indicator snapshots at all -> every asset present with null changes, no exception.
    fs = engine.compute({}, {}, {}, [], ctx)
    for symbol in ALL_SYMBOLS:
        af = fs.per_asset[symbol]
        assert af.changes.h6 is None


def test_short_series_degrades_indicators_without_error(
    engine: FeatureEngine, ctx: RunContext
) -> None:
    # A present-but-short series exercises every indicator guard branch: no indicator is emitted,
    # the run does not fail, and the result still validates.
    short = {
        "as_of": "2026-07-14T12:45:00Z",
        "closes": [100.0, 101.0, 102.0],
        "highs": [101.0, 102.0, 103.0],
        "lows": [99.0, 100.0, 101.0],
        "volumes": [1000.0, 1010.0, 1020.0],
    }
    src = MockIndicatorInputSource({s: short for s in ALL_SYMBOLS})
    ind_snaps = {s: src.fetch_series(s, ctx) for s in ALL_SYMBOLS}
    fs = engine.compute({}, ind_snaps, {}, [], ctx)
    btc = fs.per_asset["BTC"]
    assert btc.indicators == {}
    assert btc.atr_pct is None
