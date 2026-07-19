"""Unit tests for changes, surprise, and decay math."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import EventType
from market_state_engine.features import changes as ch
from market_state_engine.features import decay
from market_state_engine.features import surprise as sp


def test_pct_change_basic() -> None:
    assert ch.pct_change(110.0, 100.0) == pytest.approx(10.0)
    assert ch.pct_change(90.0, 100.0) == pytest.approx(-10.0)


def test_horizon_change_insufficient_returns_none() -> None:
    assert ch.horizon_change([100.0, 101.0], 5) is None


def test_horizon_change_value() -> None:
    closes = [100.0, 102.0, 104.0]
    assert ch.horizon_change(closes, 2) == pytest.approx(4.0)


def test_horizon_change_nonpositive_bars_raises() -> None:
    with pytest.raises(ValueError):
        ch.horizon_change([1.0, 2.0], 0)


def test_pct_change_zero_past_raises() -> None:
    with pytest.raises(ValueError):
        ch.pct_change(1.0, 0.0)


def test_compute_surprise() -> None:
    assert sp.compute_surprise(0.4, 0.3) == pytest.approx(0.1)


def test_event_feature_none_without_actual() -> None:
    ev = MacroEvent(
        event_id="e1",
        event_type=EventType.US_CPI,
        scheduled_at="2026-07-14T12:30:00Z",
        consensus=0.3,
        actual=None,
    )
    assert sp.event_feature(ev, datetime(2026, 7, 14, 13, tzinfo=timezone.utc)) is None


def test_event_feature_computed() -> None:
    ev = MacroEvent(
        event_id="us_cpi_2026_07",
        event_type=EventType.US_CPI,
        scheduled_at="2026-07-14T12:30:00Z",
        consensus=0.3,
        actual=0.4,
    )
    ef = sp.event_feature(ev, datetime(2026, 7, 14, 14, 30, tzinfo=timezone.utc))
    assert ef is not None
    assert ef.surprise == pytest.approx(0.1)
    assert ef.proximity_hours == pytest.approx(2.0)


def test_decay_factor_at_half_life_is_half() -> None:
    assert decay.decay_factor(12.0, 12.0) == pytest.approx(0.5)


def test_decay_factor_zero_elapsed_is_one() -> None:
    assert decay.decay_factor(0.0, 12.0) == 1.0


def test_decay_factor_negative_half_life_raises() -> None:
    with pytest.raises(ValueError):
        decay.decay_factor(1.0, 0.0)


def test_recency_decay_uses_injected_now() -> None:
    now = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
    # published 24h earlier, half-life 24h -> factor 0.5
    factor = decay.recency_decay("2026-07-13T12:30:00Z", now, 24.0)
    assert factor == pytest.approx(0.5, abs=1e-9)
