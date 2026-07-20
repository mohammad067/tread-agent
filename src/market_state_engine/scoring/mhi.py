"""Market Health Index in [0, 100]. Config-weighted projection. Pure.

See docs/architecture/scoring-methodology.md §4.
"""

from __future__ import annotations

from market_state_engine.config.models import MhiWeights

from .common import ATR_FULL, clamp


def market_health_index(
    weights: MhiWeights,
    trend: float,
    risk: float,
    sentiment: float | None,
    atr_pct: float | None,
) -> int:
    """Combine health components using config weights; drop absent components and renormalize.

    Health mappings (all -> [0,1], higher = healthier):
      trend      -> (trend + 1) / 2
      risk       -> 1 - risk
      sentiment  -> (sentiment + 1) / 2   (dropped when None, e.g. degraded run)
      volatility -> 1 - clamp(atr_pct / ATR_FULL, 0, 1)  (dropped when atr_pct None)
    """
    w = weights.weights
    pairs: list[tuple[float, float]] = []
    if "trend" in w:
        pairs.append(((trend + 1.0) / 2.0, w["trend"]))
    if "risk" in w:
        pairs.append((1.0 - risk, w["risk"]))
    if "sentiment" in w and sentiment is not None:
        pairs.append(((sentiment + 1.0) / 2.0, w["sentiment"]))
    if "volatility" in w and atr_pct is not None:
        pairs.append((1.0 - clamp(atr_pct / ATR_FULL, 0.0, 1.0), w["volatility"]))

    total_w = sum(weight for _, weight in pairs)
    if total_w == 0.0:
        return 50  # neutral when nothing is scoreable
    health = sum(value * weight for value, weight in pairs) / total_w
    return round(100.0 * clamp(health, 0.0, 1.0))
