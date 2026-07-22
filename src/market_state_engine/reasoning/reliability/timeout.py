"""``TimeoutPolicy`` — per-provider deadline enforcement (ADR-007 D-5, config-driven).

Deadlines are measured against an **injected monotonic clock** (milliseconds), so timeout behaviour
is deterministic and replay-safe — no wall-clock, no threads, no real sleeping. The adapter call is
wrapped: the elapsed time between the pre- and post-call reads is compared to the provider's
``timeout_seconds``; exceeding it raises ``ProviderTimeoutError`` (a call failure → next provider),
even if the underlying call ultimately returned.

Real deployments pass a monotonic source backed by ``time.monotonic_ns`` (and typically also hand
the deadline to the SDK client). Here the policy owns the *decision*; the SDK-level timeout is set
by the adapter from the same ``CallParams.timeout_seconds``.
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import ProviderTimeoutError
from ..types import RawProviderResult

Attempt = Callable[[], RawProviderResult]
MonotonicMs = Callable[[], int]


class TimeoutPolicy:
    def __init__(self, timeout_seconds: int, monotonic_ms: MonotonicMs) -> None:
        self._timeout_ms = timeout_seconds * 1000
        self._monotonic_ms = monotonic_ms

    def run(self, provider: str, attempt: Attempt) -> tuple[RawProviderResult, int]:
        """Run ``attempt`` and enforce the deadline. Returns (result, elapsed_ms)."""
        start = self._monotonic_ms()
        result = attempt()
        elapsed = max(0, self._monotonic_ms() - start)
        if elapsed > self._timeout_ms:
            raise ProviderTimeoutError(
                f"{provider}: exceeded {self._timeout_ms}ms deadline ({elapsed}ms)"
            )
        return result, elapsed
