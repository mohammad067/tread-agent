"""Shared scoring primitives: clamping and enum->scalar mappings. Pure."""

from __future__ import annotations

from market_state_engine.core.enums import EmaState, MacdState

# Tuning constants (documented in docs/architecture/scoring-methodology.md).
SCALE_24H = 5.0
SCALE_7D = 15.0
ATR_FULL = 5.0
PROX_WINDOW = 48.0
VOL_SPAN = 2.0
RISK_HI = 0.6
RISK_LO = 0.45
TREND_BAND = 0.2

_EMA_MAP: dict[EmaState, float] = {
    EmaState.ABOVE_DIVERGING: 1.0,
    EmaState.ABOVE_CONVERGING: 0.5,
    EmaState.CROSSING: 0.0,
    EmaState.BELOW_CONVERGING: -0.5,
    EmaState.BELOW_DIVERGING: -1.0,
}

_MACD_MAP: dict[MacdState, float] = {
    MacdState.BULLISH_CROSS: 1.0,
    MacdState.BULLISH: 0.5,
    MacdState.NEUTRAL: 0.0,
    MacdState.BEARISH: -0.5,
    MacdState.BEARISH_CROSS: -1.0,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ema_signal(state: str) -> float:
    return _EMA_MAP[EmaState(state)]


def macd_signal(state: str) -> float:
    return _MACD_MAP[MacdState(state)]


def rsi_signal(rsi: float) -> float:
    return clamp((rsi - 50.0) / 50.0, -1.0, 1.0)


def weighted_mean(pairs: list[tuple[float, float]]) -> float:
    """Weighted mean over (value, weight) pairs, renormalized by present weight. Empty -> 0.0."""
    total_w = sum(w for _, w in pairs)
    if total_w == 0.0:
        return 0.0
    return sum(v * w for v, w in pairs) / total_w
