"""End-to-end deterministic core: mocks -> features -> scoring -> rules -> assembly.

Produces a degraded MarketStateRun (no LLM), validates it against the frozen public schema, asserts
the degraded shape (ADR-011), and proves replay determinism (byte-identical on re-run).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from market_state_engine.assembly.deterministic_state import DeterministicStateAssembler
from market_state_engine.config.loader import load_config_bundle
from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import EventType, RegimeState, TriggerType
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.models import MarketStateRun
from market_state_engine.core.run_context import RunContext
from market_state_engine.features.engine import FeatureEngine
from market_state_engine.ingestion.mocks.mock_sources import (
    MockDominanceSource,
    MockFearGreedSource,
    MockIndicatorInputSource,
    MockPriceSource,
    MockTotalMcapSource,
)
from market_state_engine.rules.engine import RuleEngine
from market_state_engine.rules.loader import load_rulebook, read_rulebook_version
from market_state_engine.scoring.engine import ScoringEngine

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "config"
RULES_DIR = REPO / "rules"
ALL_SYMBOLS = ["BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"]


def _downtrend_series(base: float, n: int = 130) -> dict[str, Any]:
    closes = [base - 0.5 * i + 2.0 * math.sin(i / 3.0) for i in range(n)]
    return {
        "as_of": "2026-07-14T12:45:00Z",
        "value": closes[-1],
        "closes": closes,
        "highs": [c + 3.0 for c in closes],
        "lows": [c - 3.0 for c in closes],
        "volumes": [1000.0 + 40.0 * i for i in range(n)],
    }


def _run_pipeline() -> MarketStateRun:
    config = load_config_bundle(CONFIG_DIR)
    rules = load_rulebook(RULES_DIR)
    ctx = RunContext(
        run_id="01J8ZK3W9P4Q5R6S7T8U9V0W1X",
        run_sequence=1842,
        trigger_type=TriggerType.EVENT,
        now=datetime(2026, 7, 14, 12, 47, 3, tzinfo=timezone.utc),
        previous_state=RegimeState.TRANSITION,
        versions={},
    )

    series = {s: _downtrend_series(120.0 + i * 10) for i, s in enumerate(ALL_SYMBOLS)}
    ind_src = MockIndicatorInputSource(series)
    price_src = MockPriceSource(series)
    ind_snaps = {s: ind_src.fetch_series(s, ctx) for s in ALL_SYMBOLS}
    price_snaps = {s: price_src.fetch(s, ctx) for s in ALL_SYMBOLS}
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
            actual=0.45,  # surprise +0.15 -> hot CPI rule fires
        )
    ]

    features = FeatureEngine(config).compute({}, ind_snaps, global_snaps, events, ctx)
    scoring = ScoringEngine(config).score(features, ctx.previous_state, sentiment=None)
    regime_state = RegimeState(scoring.regime.state)
    activations, conflict_findings = RuleEngine(rules).match(features.event_features, regime_state)

    from market_state_engine.core.models import GuardrailFlag

    conflict_flags = [
        GuardrailFlag(code="rule_conflict", severity="warning", detail=f.detail, field=None)
        for f in conflict_findings
    ]

    assembler = DeterministicStateAssembler(config, read_rulebook_version(RULES_DIR))
    return assembler.assemble(
        ctx, features, scoring, activations, conflict_flags, price_snaps, global_snaps
    )


@pytest.mark.contract
def test_degraded_run_validates_against_schema(make_validator: Any) -> None:
    run = _run_pipeline()
    doc = json.loads(json.dumps(run.to_contract_dict()))
    validator = make_validator("market_state_run.v1.0.0.json")
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.mark.contract
def test_degraded_run_has_honest_shape() -> None:
    run = _run_pipeline().to_contract_dict()
    assert run["is_degraded"] is True
    for asset in run["assets"]:
        assert asset["scores"]["sentiment"] is None
        assert "human_summary_fa" not in asset
    codes = {f["code"] for f in run["guardrail_flags"]}
    assert "degraded_run" in codes


@pytest.mark.contract
def test_all_six_assets_present() -> None:
    run = _run_pipeline().to_contract_dict()
    symbols = {a["symbol"] for a in run["assets"]}
    assert symbols == set(ALL_SYMBOLS)


@pytest.mark.contract
def test_hot_cpi_rule_activated_and_causal_link() -> None:
    run = _run_pipeline().to_contract_dict()
    btc = next(a for a in run["assets"] if a["symbol"] == "BTC")
    rule_ids = {r["rule_id"] for r in btc["activated_rules"]}
    assert "cpi_hot_risk_assets_bearish" in rule_ids
    assert any(link["via_rule"] == "cpi_hot_risk_assets_bearish" for link in btc["causal_links"])


@pytest.mark.contract
def test_replay_determinism_byte_identical() -> None:
    a = _run_pipeline().to_contract_dict()
    b = _run_pipeline().to_contract_dict()
    assert content_hash(a) == content_hash(b)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.contract
def test_usd_irr_is_irt_and_low_sensitivity() -> None:
    run = _run_pipeline().to_contract_dict()
    usd = next(a for a in run["assets"] if a["symbol"] == "USD_IRR")
    assert usd["price"]["currency"] == "IRT"
    assert usd["regime_sensitivity"] == "low"
