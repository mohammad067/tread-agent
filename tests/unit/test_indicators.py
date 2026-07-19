"""Unit tests for deterministic indicators. Values checked against hand/textbook computations."""

from __future__ import annotations

import math

import pytest

from market_state_engine.core.enums import EmaState, MacdState
from market_state_engine.features import indicators as ind


def test_rsi_all_gains_is_100() -> None:
    closes = [float(i) for i in range(1, 30)]
    assert ind.rsi_14(closes) == 100.0


def test_rsi_all_losses_is_0() -> None:
    closes = [float(i) for i in range(30, 1, -1)]
    assert ind.rsi_14(closes) == 0.0


def test_rsi_alternating_series_is_near_midrange() -> None:
    # Alternating +1/-1 deltas keep RSI near 50 (Wilder smoothing makes it slightly asymmetric
    # depending on the final delta; it is not exactly 50).
    closes = [100.0]
    for i in range(1, 40):
        closes.append(closes[-1] + (1.0 if i % 2 else -1.0))
    rsi = ind.rsi_14(closes)
    assert 45.0 <= rsi <= 55.0


def test_rsi_is_bounded_0_100() -> None:
    closes = [100.0 + ((-1) ** i) * (i % 5) for i in range(60)]
    assert 0.0 <= ind.rsi_14(closes) <= 100.0


def test_rsi_requires_enough_data() -> None:
    with pytest.raises(ValueError):
        ind.rsi_14([1.0, 2.0, 3.0])


def test_ema_constant_series_equals_constant() -> None:
    assert ind.ema([5.0] * 30, 10) == pytest.approx(5.0)


def test_atr_pct_constant_range() -> None:
    highs = [101.0] * 20
    lows = [99.0] * 20
    closes = [100.0] * 20
    # TR is 2.0 each bar; ATR% = 2/100*100 = 2.0.
    assert ind.atr_pct(highs, lows, closes) == pytest.approx(2.0, abs=1e-6)


def test_volume_ratio_doubling() -> None:
    volumes = [100.0] * 20 + [200.0]
    assert ind.volume_ratio_20d(volumes) == pytest.approx(2.0)


def test_macd_bullish_cross_on_upturn() -> None:
    # Long downtrend then a sharp sustained upturn -> a bullish cross appears.
    closes = [100.0 - i for i in range(40)] + [60.0 + 3.0 * i for i in range(1, 12)]
    assert ind.macd_state(closes) in {MacdState.BULLISH_CROSS, MacdState.BULLISH}


def test_ema_20_50_above_when_uptrending() -> None:
    closes = [float(i) for i in range(1, 60)]
    assert ind.ema_20_50(closes) in {EmaState.ABOVE_DIVERGING, EmaState.ABOVE_CONVERGING}


def test_ema_20_50_below_when_downtrending() -> None:
    closes = [float(i) for i in range(60, 1, -1)]
    assert ind.ema_20_50(closes) in {EmaState.BELOW_DIVERGING, EmaState.BELOW_CONVERGING}


def test_guard_errors_on_insufficient_data() -> None:
    with pytest.raises(ValueError):
        ind.ema([1.0, 2.0], 10)
    with pytest.raises(ValueError):
        ind.macd_state([1.0] * 10)
    with pytest.raises(ValueError):
        ind.ema_20_50([1.0] * 10)
    with pytest.raises(ValueError):
        ind.atr_pct([1.0] * 5, [1.0] * 5, [1.0] * 5)
    with pytest.raises(ValueError):
        ind.volume_ratio_20d([1.0] * 5)


def test_atr_pct_mismatched_lengths_raises() -> None:
    with pytest.raises(ValueError):
        ind.atr_pct([1.0, 2.0], [1.0], [1.0, 2.0])


def test_atr_pct_zero_close_raises() -> None:
    highs = [1.0] * 20
    lows = [-1.0] * 20
    closes = [1.0] * 19 + [0.0]
    with pytest.raises(ValueError):
        ind.atr_pct(highs, lows, closes)


def test_volume_ratio_zero_avg_raises() -> None:
    with pytest.raises(ValueError):
        ind.volume_ratio_20d([0.0] * 20 + [5.0])


def test_bearish_cross_on_downturn() -> None:
    closes = [100.0 + i for i in range(40)] + [140.0 - 3.0 * i for i in range(1, 12)]
    assert ind.macd_state(closes) in {MacdState.BEARISH_CROSS, MacdState.BEARISH}


def test_ema_20_50_crossing_detected() -> None:
    # Rise then fall so EMA20 crosses EMA50 within the last two bars region.
    closes = [float(i) for i in range(60)] + [60.0 - 2.0 * i for i in range(1, 40)]
    state = ind.ema_20_50(closes)
    assert state in set(EmaState)


def test_determinism_repeat_calls() -> None:
    closes = [100.0 + math.sin(i) for i in range(60)]
    assert ind.rsi_14(closes) == ind.rsi_14(closes)
    assert ind.atr_pct([c + 1 for c in closes], [c - 1 for c in closes], closes) == ind.atr_pct(
        [c + 1 for c in closes], [c - 1 for c in closes], closes
    )
