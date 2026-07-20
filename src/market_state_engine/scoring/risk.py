"""Risk score in [0, 1]. Pure. See docs/architecture/scoring-methodology.md §2."""

from __future__ import annotations

from market_state_engine.core.dtos import AssetFeatures

from .common import ATR_FULL, PROX_WINDOW, VOL_SPAN, clamp, weighted_mean


def risk_score(features: AssetFeatures, event_proximity_hours: float | None = None) -> float:
    pairs: list[tuple[float, float]] = []
    if features.atr_pct is not None:
        pairs.append((clamp(features.atr_pct / ATR_FULL, 0.0, 1.0), 0.50))
    if event_proximity_hours is not None:
        proximity = clamp(1.0 - abs(event_proximity_hours) / PROX_WINDOW, 0.0, 1.0)
        pairs.append((proximity, 0.30))
    if features.volume_ratio_20d is not None:
        pairs.append((clamp((features.volume_ratio_20d - 1.0) / VOL_SPAN, 0.0, 1.0), 0.20))
    return clamp(weighted_mean(pairs), 0.0, 1.0)
