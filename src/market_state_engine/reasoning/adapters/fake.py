"""``FakeProvider`` — a canned, offline provider double (frozen invariant #10 / ADR-007 D-9).

Returns pre-seeded responses for wiring and tests without touching the network or any vendor SDK.
It implements the same ``ProviderAdapter`` interface as the real vendors, so the Gateway cannot tell
it apart. Two ways to drive it:
  - fixed text/result for every call, or
  - a per-call queue of results (to script a sequence).

This is NOT the ReplayProvider (deferred): it serves canned values, not recorded Call Records.
"""

from __future__ import annotations

from collections import deque

from ..errors import ProviderCallError
from ..types import CallParams, RawProviderResult, RenderedPrompt


class FakeProvider:
    def __init__(
        self,
        name: str = "fake",
        *,
        text: str | None = None,
        result: RawProviderResult | None = None,
        results: list[RawProviderResult] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._name = name
        self._raise = raise_exc
        self._queue: deque[RawProviderResult] = deque(results or [])
        if result is not None:
            self._fixed: RawProviderResult | None = result
        elif text is not None:
            self._fixed = RawProviderResult(text=text, finish_reason="stop")
        else:
            self._fixed = None
        # Record what the Gateway sent, for test assertions.
        self.calls: list[tuple[RenderedPrompt, CallParams]] = []

    @property
    def name(self) -> str:
        return self._name

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        self.calls.append((prompt, params))
        if self._raise is not None:
            raise self._raise
        if self._queue:
            return self._queue.popleft()
        if self._fixed is not None:
            return self._fixed
        raise ProviderCallError(f"{self._name}: no canned response configured")
