"""Macro-event surprise computation. Surprise = actual - consensus (event-natural units).

The LLM never computes this; rules trigger on surprise, not raw actuals (F-5).
"""

from __future__ import annotations

from datetime import datetime

from market_state_engine.core.dtos import EventFeature, MacroEvent


def compute_surprise(actual: float, consensus: float) -> float:
    return actual - consensus


def _parse_iso(ts: str) -> datetime:
    # Python 3.10 fromisoformat handles offsets like +03:30 and 'Z' via replacement.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def proximity_hours(event_time: str, now: datetime) -> float:
    """Signed hours from ``now`` to the event (positive = event in the past)."""
    delta = now - _parse_iso(event_time)
    return delta.total_seconds() / 3600.0


def event_feature(
    event: MacroEvent,
    now: datetime,
    surprise_sigma: float | None = None,
) -> EventFeature | None:
    """Build an EventFeature; returns None if the actual has not been recorded yet."""
    if event.actual is None:
        return None
    surprise = compute_surprise(event.actual, event.consensus)
    return EventFeature(
        event_id=event.event_id,
        event_type=event.event_type.value,
        surprise=surprise,
        surprise_sigma=surprise_sigma,
        proximity_hours=proximity_hours(event.scheduled_at, now),
    )
