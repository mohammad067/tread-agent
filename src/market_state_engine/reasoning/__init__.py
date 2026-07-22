"""Reasoning layer — the provider-agnostic LLM boundary (frozen ADR-007 / ADR-011).

The deterministic core depends on exactly one type from here — the ``MarketReasoner`` port — and
nothing below it. Everything vendor-specific is selected by configuration and lives behind the port:
``LLMGateway`` (the production ``MarketReasoner``) owns routing, retry, timeout, failover, circuit
breaking, health, Call Record capture, cost, and the honest Degraded Run; ``PromptBuilder`` renders
vendor-neutral prompts; provider adapters translate to/from each vendor; ``ReplayProvider``
reproduces recorded runs offline.

Public surface (stable): the port + neutral DTOs, and the ``integration`` facade that wires a fully
configured gateway (live or replay) from a project root. Import the facade — not concrete adapters —
from outside the reasoning layer.
"""

from __future__ import annotations

from .gateway import LLMGateway
from .integration import ReasoningPaths, build_gateway, build_replay_gateway
from .models import (
    CallRecord,
    DegradedMarker,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)
from .port import MarketReasoner

__all__ = [
    "CallRecord",
    "DegradedMarker",
    "LLMGateway",
    "MarketReasoner",
    "ReasoningPaths",
    "ReasoningRequest",
    "SentimentResponse",
    "SynthesisResponse",
    "build_gateway",
    "build_replay_gateway",
]
