"""``HealthMonitor`` — rolling per-provider success/latency/timeout stats (ADR-007 D-7).

Feeds dashboards, alerts, and (optionally) routing eligibility. **Operational only**: nothing here
ever influences a market score, regime, rule, or MHI — it changes *routing*, never *market truth*
(the hard wall of ADR-007 D-7 / llm-provider-architecture §6). Stats are computed from the same
call outcomes the Call Records capture; this monitor keeps a bounded in-memory rolling view for
the Gateway and metrics exporter.

Bounded to the last ``window`` outcomes per provider so memory stays flat over a long process.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..outcome import Outcome


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    samples: int
    successes: int
    failures: int
    timeouts: int
    circuit_opens: int
    success_rate: float
    timeout_rate: float
    avg_latency_ms: float


class _Rolling:
    __slots__ = ("latencies", "outcomes")

    def __init__(self, window: int) -> None:
        self.outcomes: deque[str] = deque(maxlen=window)
        self.latencies: deque[int] = deque(maxlen=window)


class HealthMonitor:
    def __init__(self, window: int = 50) -> None:
        self._window = window
        self._by_provider: dict[str, _Rolling] = {}

    def _roll(self, provider: str) -> _Rolling:
        roll = self._by_provider.get(provider)
        if roll is None:
            roll = _Rolling(self._window)
            self._by_provider[provider] = roll
        return roll

    def record(self, provider: str, outcome: str, latency_ms: int) -> None:
        roll = self._roll(provider)
        roll.outcomes.append(outcome)
        if outcome == Outcome.SUCCESS.value:
            roll.latencies.append(max(0, latency_ms))

    def snapshot(self, provider: str) -> ProviderHealth:
        roll = self._by_provider.get(provider)
        if roll is None or not roll.outcomes:
            return ProviderHealth(provider, 0, 0, 0, 0, 0, 1.0, 0.0, 0.0)
        samples = len(roll.outcomes)
        successes = sum(1 for o in roll.outcomes if o == Outcome.SUCCESS.value)
        timeouts = sum(1 for o in roll.outcomes if o == Outcome.TIMEOUT.value)
        circuit_opens = sum(1 for o in roll.outcomes if o == Outcome.CIRCUIT_OPEN.value)
        failures = samples - successes
        avg_latency = sum(roll.latencies) / len(roll.latencies) if roll.latencies else 0.0
        return ProviderHealth(
            provider=provider,
            samples=samples,
            successes=successes,
            failures=failures,
            timeouts=timeouts,
            circuit_opens=circuit_opens,
            success_rate=successes / samples,
            timeout_rate=timeouts / samples,
            avg_latency_ms=avg_latency,
        )

    def all_snapshots(self) -> dict[str, ProviderHealth]:
        return {name: self.snapshot(name) for name in self._by_provider}
