"""Reliability layer — the resilience machinery under the ``MarketReasoner`` boundary (M4.3).

Config-driven per ADR-007 D-5 and the ADR-011 failover chain:

    call provider[i] (retry+timeout per its policy) → on failure mark health, maybe trip breaker
        → next healthy provider[i+1] … → all exhausted → DEGRADED RUN (never abort)

Every component here is **operational only** (ADR-007 D-7): it changes *routing*, never any market
number. All time is injected (``monotonic``/``sleep``) so behaviour is deterministic and replay-
safe; nothing here does real I/O or reaches the network.
"""

from __future__ import annotations

from .circuit_breaker import BreakerState, CircuitBreaker, CircuitBreakerRegistry
from .health import HealthMonitor, ProviderHealth
from .retry import RetryPolicy
from .router import Router
from .timeout import TimeoutPolicy

__all__ = [
    "BreakerState",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "HealthMonitor",
    "ProviderHealth",
    "RetryPolicy",
    "Router",
    "TimeoutPolicy",
]
