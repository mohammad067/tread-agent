"""``CircuitBreaker`` — trip a failing provider out of rotation; half-open probe to recover.

State machine (ADR-007 D-5 / llm-provider-architecture §7), config-driven via ``CircuitBreakerCfg``:

    CLOSED   — calls allowed. Failures within ``window_seconds`` accumulate; on reaching
               ``failure_threshold`` the breaker OPENS.
    OPEN     — calls skipped (``CircuitOpenError``) until ``half_open_after_seconds`` elapses since
               it opened, then it moves to HALF_OPEN.
    HALF_OPEN — a single probe call is allowed. Success → CLOSED (counters reset); failure → OPEN
               again (timer restarts).

Time is an injected monotonic-seconds reader, so the breaker is deterministic and replay-safe. It is
**operational only** — it changes routing eligibility, never any market number (ADR-007 D-7).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from enum import Enum

from ..provider_config import CircuitBreakerCfg

MonotonicSeconds = Callable[[], float]


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, cfg: CircuitBreakerCfg, monotonic_s: MonotonicSeconds) -> None:
        self._cfg = cfg
        self._now = monotonic_s
        self._failures: deque[float] = deque()
        self._state = BreakerState.CLOSED
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        # Resolve a pending OPEN → HALF_OPEN transition lazily on inspection.
        self._maybe_half_open()
        return self._state

    def allows(self) -> bool:
        """Whether a call may be attempted now (CLOSED or a HALF_OPEN probe)."""
        return self.state is not BreakerState.OPEN

    def _maybe_half_open(self) -> None:
        if (
            self._state is BreakerState.OPEN
            and self._opened_at is not None
            and self._now() - self._opened_at >= self._cfg.half_open_after_seconds
        ):
            self._state = BreakerState.HALF_OPEN

    def _prune(self, now: float) -> None:
        horizon = now - self._cfg.window_seconds
        while self._failures and self._failures[0] < horizon:
            self._failures.popleft()

    def record_success(self) -> None:
        # A success (including a half-open probe) closes the breaker and clears history.
        self._failures.clear()
        self._state = BreakerState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        now = self._now()
        if self.state is BreakerState.HALF_OPEN:
            # A failed probe re-opens immediately and restarts the cool-down.
            self._trip(now)
            return
        self._failures.append(now)
        self._prune(now)
        if len(self._failures) >= self._cfg.failure_threshold:
            self._trip(now)

    def _trip(self, now: float) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = now
        self._failures.clear()


class CircuitBreakerRegistry:
    """One breaker per provider, sharing the same config + injected clock."""

    def __init__(self, cfg: CircuitBreakerCfg, monotonic_s: MonotonicSeconds) -> None:
        self._cfg = cfg
        self._now = monotonic_s
        self._breakers: dict[str, CircuitBreaker] = {}

    def for_provider(self, name: str) -> CircuitBreaker:
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(self._cfg, self._now)
            self._breakers[name] = breaker
        return breaker
