"""Multi-horizon percentage changes (6h / 24h / 7d / 30d). Pure."""

from __future__ import annotations

# Horizon -> number of trailing bars back, assuming a fixed bar interval documented by the caller.
# The FeatureEngine supplies close series with a known cadence; here we compute % change vs a
# reference close N bars back. A missing/insufficient horizon returns None (declared as a data gap).درصد تغییر قیمت


def pct_change(current: float, past: float) -> float:
    if past == 0:
        raise ValueError("pct_change: past value is zero")
    return (current - past) / past * 100.0


def horizon_change(closes: list[float], bars_back: int) -> float | None:
    """Percent change of the latest close vs the close ``bars_back`` bars earlier.

    Returns None when the series is too short (the caller records a data gap)."""
    if bars_back <= 0:
        raise ValueError("bars_back must be positive")
    if len(closes) <= bars_back:
        return None
    return pct_change(closes[-1], closes[-1 - bars_back])
