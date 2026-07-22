"""``MarketReasoner`` — the ONLY LLM-facing type the core may reference (ADR-007 D-1).

Two operations, exactly the two LLM calls of ADR-002: ``analyze_sentiment`` and ``synthesize``.
Both take a provider-neutral ``ReasoningRequest`` and return either a validated response variant or
a ``DegradedMarker`` (ADR-011) — never a fabricated result. The port names no vendor and contains no
logic; the ``LLMGateway`` is its production implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    DegradedMarker,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)


@runtime_checkable
class MarketReasoner(Protocol):
    def analyze_sentiment(
        self, request: ReasoningRequest
    ) -> SentimentResponse | DegradedMarker: ...

    def synthesize(self, request: ReasoningRequest) -> SynthesisResponse | DegradedMarker: ...
