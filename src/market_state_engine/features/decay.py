"""Half-life decay math for news recency and rule influence. Pure.

decay(t) = 0.5 ** (elapsed_hours / half_life_hours), clamped to [0, 1].
"""

from __future__ import annotations

from datetime import datetime


def decay_factor(elapsed_hours: float, half_life_hours: float) -> float:
    if half_life_hours <= 0:
        raise ValueError("half_life_hours must be positive")
    if elapsed_hours <= 0:
        return 1.0
    value: float = 0.5 ** (elapsed_hours / half_life_hours)
    return max(0.0, min(1.0, value))


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def recency_decay(published_at: str, now: datetime, half_life_hours: float) -> float:
    elapsed = (now - _parse_iso(published_at)).total_seconds() / 3600.0
    return decay_factor(elapsed, half_life_hours)
