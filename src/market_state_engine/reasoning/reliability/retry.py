"""``RetryPolicy`` — per-provider attempt + backoff enforcement (ADR-007 D-5, config-driven).

A provider is attempted up to ``retries + 1`` times (the initial call plus ``retries`` re-tries).
Only ``ProviderCallError`` (including timeout) is retryable — a ``StructuredOutputError`` is a
content failure that a re-try would not fix, so it is raised immediately to move to the next
provider. Backoff is exponential with a cap, computed from ``BackoffCfg``; the sleep function is
injected so tests run instantly and behaviour stays deterministic (no wall-clock).

The policy retries a *single provider*; the failover across providers is the Router/Gateway's job.
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import ProviderCallError, StructuredOutputError
from ..provider_config import BackoffCfg
from ..types import RawProviderResult

Attempt = Callable[[], RawProviderResult]
Sleep = Callable[[float], None]


def _no_sleep(_seconds: float) -> None:
    """Default sleep: do nothing (deterministic). Real deployments inject ``time.sleep``."""


class RetryPolicy:
    def __init__(self, retries: int, backoff: BackoffCfg, sleep: Sleep = _no_sleep) -> None:
        self._retries = max(0, retries)
        self._backoff = backoff
        self._sleep = sleep

    @property
    def max_attempts(self) -> int:
        return self._retries + 1

    def backoff_ms(self, attempt_index: int) -> int:
        """Backoff before the retry following ``attempt_index`` (0-based); capped at ``max_ms``."""
        if self._backoff.type != "exponential":
            return min(self._backoff.base_ms, self._backoff.max_ms)
        raw: int = self._backoff.base_ms * (2**attempt_index)
        return min(raw, self._backoff.max_ms)

    def run(self, attempt: Attempt) -> tuple[RawProviderResult, int]:
        """Run ``attempt`` with retries. Returns (result, retries_used) or raises the last error.

        ``retries_used`` is the number of *re-tries* (0 = succeeded first try) — recorded on the
        Call Record.
        """
        last_exc: ProviderCallError | None = None
        for i in range(self.max_attempts):
            try:
                return attempt(), i
            except StructuredOutputError:
                # Content failure: retrying the same provider won't help — surface immediately.
                raise
            except ProviderCallError as exc:
                last_exc = exc
                if i < self.max_attempts - 1:
                    self._sleep(self.backoff_ms(i) / 1000.0)
        # Exhausted all attempts for this provider.
        assert last_exc is not None
        raise last_exc
