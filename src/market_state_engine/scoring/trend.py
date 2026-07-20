"""Trend score in [-1, 1]. Pure. See docs/architecture/scoring-methodology.md §1."""

from __future__ import annotations

from market_state_engine.core.dtos import AssetFeatures

from .common import (
    SCALE_7D,
    SCALE_24H,
    clamp,
    ema_signal,
    macd_signal,
    rsi_signal,
    weighted_mean,
)


def trend_subsignals(features: AssetFeatures) -> list[tuple[float, float]]:
    """Return (signal, weight) pairs for each present trend component."""
    pairs: list[tuple[float, float]] = []
    ind = features.indicators or {}
    ema = ind.get("ema_20_50")
    if isinstance(ema, str):
        pairs.append((ema_signal(ema), 0.30))
    macd = ind.get("macd_state")
    if isinstance(macd, str):
        pairs.append((macd_signal(macd), 0.25))
    rsi = ind.get("rsi_14")
    if isinstance(rsi, (int, float)):
        pairs.append((rsi_signal(float(rsi)), 0.15))
    if features.changes.h24 is not None:
        pairs.append((clamp(features.changes.h24 / SCALE_24H, -1.0, 1.0), 0.15))
    if features.changes.d7 is not None:
        pairs.append((clamp(features.changes.d7 / SCALE_7D, -1.0, 1.0), 0.15))
    return pairs


def trend_score(features: AssetFeatures) -> float:
    return clamp(weighted_mean(trend_subsignals(features)), -1.0, 1.0)
