"""RegimeClassifier: deterministic global regime, computed first (ADR-005). Pure.

Uses macro-style inputs (cross-asset trend/risk, active event surprise), never crypto Fear & Greed
(A6). Excludes regime_sensitivity: low assets (USD/IRR) from the aggregates.
See docs/architecture/scoring-methodology.md §5.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from market_state_engine.core.dtos import EventFeature, RegimeResult
from market_state_engine.core.enums import RegimeSensitivity, RegimeState

from .common import RISK_HI, RISK_LO, TREND_BAND, clamp

_EVENT_MATERIAL_SURPRISE = 0.05  # |surprise| threshold for event_driven regime
_EVENT_WINDOW_HOURS = 48.0


@dataclass(frozen=True)
class AssetRegimeInput:
    symbol: str
    trend: float
    risk: float
    regime_sensitivity: RegimeSensitivity


def _active_material_event(events: list[EventFeature]) -> EventFeature | None:
    material: list[EventFeature] = [
        e
        for e in events
        if abs(e.proximity_hours) <= _EVENT_WINDOW_HOURS
        and abs(e.surprise) >= _EVENT_MATERIAL_SURPRISE
    ]
    if not material:
        return None
    # Deterministic pick: strongest surprise, tie-broken by event_id.
    return max(material, key=lambda e: (abs(e.surprise), e.event_id))


def classify(
    assets: list[AssetRegimeInput],
    events: list[EventFeature],
    previous_state: RegimeState | None,
) -> RegimeResult:
    sensitive = [a for a in assets if a.regime_sensitivity is not RegimeSensitivity.LOW]
    event = _active_material_event(events)

    if event is not None:
        state = RegimeState.EVENT_DRIVEN
        margin = clamp(
            (abs(event.surprise) - _EVENT_MATERIAL_SURPRISE) / max(_EVENT_MATERIAL_SURPRISE, 1e-9),
            0.0,
            1.0,
        )
        concordance = _trend_concordance(sensitive)
        drivers: list[dict[str, object]] = [
            {
                "name": f"event_{event.event_type}",
                "weight_type": "computed",
                "weight": round(clamp(0.4 + 0.4 * margin, 0.0, 1.0), 4),
                "detail": f"surprise={event.surprise}",
            }
        ]
    else:
        avg_trend = _mean(a.trend for a in sensitive)
        avg_risk = _mean(a.risk for a in sensitive)
        state = _state_from_aggregates(avg_trend, avg_risk)
        margin = _boundary_margin(avg_trend, avg_risk, state)
        concordance = _trend_concordance(sensitive)
        drivers = [
            {
                "name": "avg_trend",
                "weight_type": "computed",
                "weight": round((avg_trend + 1) / 2, 4),
            },
            {"name": "avg_risk", "weight_type": "computed", "weight": round(avg_risk, 4)},
        ]

    confidence = clamp(0.5 * margin + 0.5 * concordance, 0.0, 1.0)
    prev = previous_state.value if previous_state is not None else None
    return RegimeResult(
        state=state.value,
        previous_state=prev,
        changed_this_run=(state.value != prev),
        confidence=round(confidence, 4),
        computed_drivers=drivers,
    )


def _state_from_aggregates(avg_trend: float, avg_risk: float) -> RegimeState:
    if avg_risk >= RISK_HI and avg_trend <= -TREND_BAND:
        return RegimeState.RISK_OFF
    if avg_risk <= RISK_LO and avg_trend >= TREND_BAND:
        return RegimeState.RISK_ON
    return RegimeState.TRANSITION


def _boundary_margin(avg_trend: float, avg_risk: float, state: RegimeState) -> float:
    """Normalized distance from the nearest classification boundary (deeper -> higher)."""
    if state is RegimeState.RISK_OFF:
        d = min(avg_risk - RISK_HI, -TREND_BAND - avg_trend)
        return clamp(d / 0.4, 0.0, 1.0)
    if state is RegimeState.RISK_ON:
        d = min(RISK_LO - avg_risk, avg_trend - TREND_BAND)
        return clamp(d / 0.4, 0.0, 1.0)
    # transition: margin is how centered it is between the bands (low margin near a boundary).
    dist_to_off = min(abs(avg_risk - RISK_HI), abs(avg_trend + TREND_BAND))
    dist_to_on = min(abs(avg_risk - RISK_LO), abs(avg_trend - TREND_BAND))
    return clamp(min(dist_to_off, dist_to_on) / 0.3, 0.0, 1.0)


def _trend_concordance(assets: list[AssetRegimeInput]) -> float:
    if not assets:
        return 0.5
    avg = _mean(a.trend for a in assets)
    ref = 1.0 if avg >= 0 else -1.0
    agree = sum(1 for a in assets if (a.trend >= 0) == (ref >= 0))
    return agree / len(assets)


def _mean(values: Iterable[float]) -> float:
    seq = list(values)
    return sum(seq) / len(seq) if seq else 0.0
