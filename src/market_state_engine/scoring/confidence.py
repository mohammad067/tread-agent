"""Deterministic system confidence in [0, 1]. Pure. Never a probability (A2).

See docs/architecture/scoring-methodology.md §3.
"""

from __future__ import annotations

from market_state_engine.core.dtos import AssetFeatures

from .common import clamp
from .trend import trend_subsignals


def _concordance(subsignals: list[tuple[float, float]]) -> float:
    """1 - normalized mean-absolute-deviation of trend sub-signals (each in [-1,1]).

    Agreeing signals -> low dispersion -> high concordance. With <2 signals, concordance is neutral
    (0.5) since agreement is undefined.
    """
    values = [v for v, _ in subsignals]
    if len(values) < 2:
        return 0.5
    mean = sum(values) / len(values)
    mad = sum(abs(v - mean) for v in values) / len(values)
    # Max possible MAD for values in [-1,1] is 1.0; normalize and invert.
    return clamp(1.0 - mad, 0.0, 1.0)


def system_confidence(features: AssetFeatures, expected_signals: int) -> float:
    subsignals = trend_subsignals(features)
    present = len(subsignals)
    completeness = clamp(present / expected_signals, 0.0, 1.0) if expected_signals > 0 else 0.0
    concordance = _concordance(subsignals)
    return clamp(0.5 * completeness + 0.5 * concordance, 0.0, 1.0)
