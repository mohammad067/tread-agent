"""Deterministic technical indicators over OHLCV series.

All functions are pure: same inputs -> same outputs, no I/O, no clock. Series are ordered oldest
-> newest closes (and volumes where needed). Standard textbook definitions; the Trader persona
reviews semantics in scoring-methodology (M3.6+), but the arithmetic lives here.
"""

from __future__ import annotations

from market_state_engine.core.enums import EmaState, MacdState


def rsi_14(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI. Requires at least ``period + 1`` closes."""
    if len(closes) < period + 1:
        raise ValueError(f"rsi_14 needs >= {period + 1} closes, got {len(closes)}")
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ema(values: list[float], period: int) -> float:
    """Exponential moving average (final value)."""
    if len(values) < period:
        raise ValueError(f"ema needs >= {period} values, got {len(values)}")
    k = 2.0 / (period + 1)
    result = sum(values[:period]) / period  # seed with SMA
    for v in values[period:]:
        result = v * k + result * (1.0 - k)
    return result


def _ema_series(values: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def macd_state(closes: list[float]) -> MacdState:
    """MACD state from 12/26 EMA and its 9-period signal; judges the last two bars for a cross."""
    if len(closes) < 26 + 9:
        raise ValueError("macd_state needs >= 35 closes")
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    # Align tails to equal length.
    n = min(len(ema12), len(ema26))
    macd_line = [ema12[-n + i] - ema26[-n + i] for i in range(n)]
    signal = _ema_series(macd_line, 9)
    m = min(len(macd_line), len(signal))
    macd_tail = macd_line[-m:]
    sig_tail = signal[-m:]
    prev_diff = macd_tail[-2] - sig_tail[-2]
    curr_diff = macd_tail[-1] - sig_tail[-1]
    if prev_diff <= 0 < curr_diff:
        return MacdState.BULLISH_CROSS
    if prev_diff >= 0 > curr_diff:
        return MacdState.BEARISH_CROSS
    if curr_diff > 0:
        return MacdState.BULLISH
    if curr_diff < 0:
        return MacdState.BEARISH
    return MacdState.NEUTRAL


def ema_20_50(closes: list[float]) -> EmaState:
    """Relationship of EMA20 vs EMA50, and whether the gap is widening or narrowing."""
    if len(closes) < 51:
        raise ValueError("ema_20_50 needs >= 51 closes")
    e20 = _ema_series(closes, 20)
    e50 = _ema_series(closes, 50)
    n = min(len(e20), len(e50))
    gap_prev = e20[-2] - e50[-2] if n >= 2 else e20[-1] - e50[-1]
    gap_now = e20[-1] - e50[-1]
    above = gap_now > 0
    # Crossing: sign changed between the last two gaps.
    if (gap_prev > 0) != (gap_now > 0):
        return EmaState.CROSSING
    widening = abs(gap_now) >= abs(gap_prev)
    if above:
        return EmaState.ABOVE_DIVERGING if widening else EmaState.ABOVE_CONVERGING
    return EmaState.BELOW_DIVERGING if widening else EmaState.BELOW_CONVERGING


def atr_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range as a percentage of the latest close."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("atr_pct requires equal-length high/low/close series")
    if len(closes) < period + 1:
        raise ValueError(f"atr_pct needs >= {period + 1} bars")
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    last_close = closes[-1]
    if last_close == 0:
        raise ValueError("atr_pct: latest close is zero")
    return (atr / last_close) * 100.0


def volume_ratio_20d(volumes: list[float], period: int = 20) -> float:
    """Latest volume relative to the trailing ``period``-average (excluding the latest bar)."""
    if len(volumes) < period + 1:
        raise ValueError(f"volume_ratio_20d needs >= {period + 1} volumes")
    window = volumes[-period - 1 : -1]
    avg = sum(window) / period
    if avg == 0:
        raise ValueError("volume_ratio_20d: trailing average volume is zero")
    return volumes[-1] / avg
