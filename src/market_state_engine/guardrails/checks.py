"""Deterministic guardrail checks. Pure functions returning GuardrailFlag-shaped findings.

Each check takes an assembled MarketStateRun candidate (as a validated model) and returns a list of
findings. Checks never mutate scores; they only flag.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_state_engine.core.enums import EmaState, MacdState, Severity
from market_state_engine.core.models import MarketStateRun


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    detail: str
    field: str | None = None


def check_degraded_honesty(run: MarketStateRun) -> list[Finding]:
    """A degraded run must not carry LLM-produced fields; a non-degraded run must (ADR-011)."""
    findings: list[Finding] = []
    for i, asset in enumerate(run.assets):
        if run.is_degraded:
            if asset.scores.sentiment is not None:
                findings.append(
                    Finding(
                        "degraded_sentiment_present",
                        Severity.CRITICAL,
                        f"{asset.symbol}: sentiment present on a degraded run",
                        f"assets[{i}].scores.sentiment",
                    )
                )
            if asset.human_summary_fa is not None:
                findings.append(
                    Finding(
                        "degraded_summary_present",
                        Severity.CRITICAL,
                        f"{asset.symbol}: human_summary_fa present on a degraded run",
                        f"assets[{i}].human_summary_fa",
                    )
                )
    return findings


def check_causal_links_resolve(run: MarketStateRun) -> list[Finding]:
    """Every causal link's via_rule must resolve to an activated rule in the run."""
    activated = {act.rule_id for asset in run.assets for act in asset.activated_rules}
    findings: list[Finding] = []
    for i, asset in enumerate(run.assets):
        for j, link in enumerate(asset.causal_links):
            if link.via_rule not in activated:
                findings.append(
                    Finding(
                        "dangling_causal_link",
                        Severity.CRITICAL,
                        f"{asset.symbol}: causal link via_rule '{link.via_rule}' not activated",
                        f"assets[{i}].causal_links[{j}]",
                    )
                )
    return findings


def check_trend_indicator_consistency(run: MarketStateRun) -> list[Finding]:
    """Flag strongly negative trend while all indicators read bullish (and vice-versa)."""
    findings: list[Finding] = []
    for i, asset in enumerate(run.assets):
        ind = asset.indicators
        if ind is None:
            continue
        bullish_signals = _bullishness(ind.macd_state, ind.ema_20_50)
        if bullish_signals is None:
            continue
        if bullish_signals is True and asset.scores.trend <= -0.5:
            findings.append(
                Finding(
                    "trend_indicator_contradiction",
                    Severity.WARNING,
                    f"{asset.symbol}: bullish indicators but strongly negative trend",
                    f"assets[{i}].scores.trend",
                )
            )
        elif bullish_signals is False and asset.scores.trend >= 0.5:
            findings.append(
                Finding(
                    "trend_indicator_contradiction",
                    Severity.WARNING,
                    f"{asset.symbol}: bearish indicators but strongly positive trend",
                    f"assets[{i}].scores.trend",
                )
            )
    return findings


def check_regime_change_flag(run: MarketStateRun) -> list[Finding]:
    """changed_this_run must be consistent with state vs previous_state."""
    regime = run.regime
    prev = regime.previous_state.value if regime.previous_state is not None else None
    expected = regime.state.value != prev
    if regime.changed_this_run != expected:
        return [
            Finding(
                "regime_change_flag_inconsistent",
                Severity.WARNING,
                "changed_this_run does not match state vs previous_state",
                "regime.changed_this_run",
            )
        ]
    return []


def _bullishness(macd: MacdState | None, ema: EmaState | None) -> bool | None:
    macd_v = macd.value if macd is not None else None
    ema_v = ema.value if ema is not None else None
    if macd_v is None or ema_v is None:
        return None
    macd_bull = macd_v in {"bullish", "bullish_cross"}
    macd_bear = macd_v in {"bearish", "bearish_cross"}
    ema_bull = ema_v in {"above_diverging", "above_converging"}
    ema_bear = ema_v in {"below_diverging", "below_converging"}
    if macd_bull and ema_bull:
        return True
    if macd_bear and ema_bear:
        return False
    return None


ALL_CHECKS = (
    check_degraded_honesty,
    check_causal_links_resolve,
    check_trend_indicator_consistency,
    check_regime_change_flag,
)
