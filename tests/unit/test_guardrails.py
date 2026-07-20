"""Guardrails checks + engine tests, driven off the golden fixtures."""

from __future__ import annotations

import copy
from typing import Any

from market_state_engine.core.enums import Severity
from market_state_engine.core.models import MarketStateRun
from market_state_engine.guardrails import checks
from market_state_engine.guardrails.engine import validate


def _run(load_golden_json: Any, name: str) -> MarketStateRun:
    return MarketStateRun.model_validate(load_golden_json(name))


def test_clean_normal_run_publishes(load_golden_json: Any) -> None:
    run = _run(load_golden_json, "market_state_run.normal.json")
    result = validate(run)
    assert result.publish is True
    assert all(f.severity is not Severity.CRITICAL for f in result.flags)


def test_degraded_run_publishes_with_flag(load_golden_json: Any) -> None:
    run = _run(load_golden_json, "market_state_run.degraded.json")
    result = validate(run)
    assert result.publish is True
    codes = {f.code for f in result.flags}
    assert "degraded_run" in codes


def test_dangling_causal_link_blocks(load_golden_json: Any) -> None:
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["assets"][0]["causal_links"][0]["via_rule"] = "nonexistent_rule"
    run = MarketStateRun.model_validate(doc)
    findings = checks.check_causal_links_resolve(run)
    assert findings
    assert findings[0].severity is Severity.CRITICAL
    assert validate(run).publish is False


def test_degraded_honesty_flags_sentiment_present(load_golden_json: Any) -> None:
    doc = copy.deepcopy(load_golden_json("market_state_run.degraded.json"))
    doc["assets"][0]["scores"]["sentiment"] = 0.1  # dishonest on a degraded run
    run = MarketStateRun.model_validate(doc)
    findings = checks.check_degraded_honesty(run)
    assert any(f.code == "degraded_sentiment_present" for f in findings)


def test_trend_indicator_contradiction_flag(load_golden_json: Any) -> None:
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    asset = doc["assets"][0]
    asset["indicators"]["macd_state"] = "bullish"
    asset["indicators"]["ema_20_50"] = "above_diverging"
    asset["scores"]["trend"] = -0.9  # bullish indicators, strongly negative trend
    run = MarketStateRun.model_validate(doc)
    findings = checks.check_trend_indicator_consistency(run)
    assert any(f.code == "trend_indicator_contradiction" for f in findings)


def test_regime_change_flag_inconsistency(load_golden_json: Any) -> None:
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["regime"]["changed_this_run"] = False  # but previous != state in the fixture
    run = MarketStateRun.model_validate(doc)
    findings = checks.check_regime_change_flag(run)
    assert findings
