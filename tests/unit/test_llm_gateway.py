"""LLMGateway skeleton tests (M4.1): port behavior, honest degraded, Call Record emission.

Uses an in-test fake adapter (a test double — the only providers that exist in M4.1). No retry,
failover, or circuit breaker is exercised; those arrive in M4.2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_state_engine.core.enums import LlmJob
from market_state_engine.reasoning.gateway import LLMGateway
from market_state_engine.reasoning.models import (
    CallRecord,
    DegradedMarker,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)
from market_state_engine.reasoning.port import MarketReasoner
from market_state_engine.reasoning.prompt_builder import PromptBuilder
from market_state_engine.reasoning.registry import ProviderRegistry
from market_state_engine.reasoning.structured_output import StructuredOutputValidator
from market_state_engine.reasoning.types import CallParams, RawProviderResult, RenderedPrompt

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "prompts"
INTERNAL_SCHEMAS = REPO / "schemas" / "internal"


class _FakeAdapter:
    """A canned in-test provider double (allowed offline seam — frozen invariant #10)."""

    def __init__(self, name: str, text: str, *, raise_exc: Exception | None = None) -> None:
        self._name = name
        self._text = text
        self._raise = raise_exc
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return RawProviderResult(
            text=self._text, input_tokens=100, output_tokens=20, finish_reason="stop"
        )


def _registry() -> ProviderRegistry:
    return ProviderRegistry.from_mapping(
        {
            "version": "1.0.0",
            "routing": {"strategy": "priority", "degrade_after_all_fail": True},
            "defaults": {"temperature": 0, "max_tokens": 512, "timeout_seconds": 20, "retries": 2},
            "providers": [
                {
                    "name": "fake",
                    "enabled": True,
                    "priority": 1,
                    "weight": 100,
                    "api_key_env": "FAKE_KEY",
                    "models": {"sentiment": "fake-1", "synthesis": "fake-1"},
                }
            ],
        }
    )


def _sentiment_request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "01J8ZK3W9P4Q5R6S7T8U9V0W1X",
            "job": "sentiment",
            "payload": {"assets": ["BTC"], "news_digest": {"run_id": "r1", "items": []}},
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SentimentResponse",
                "max_tokens": 512,
                "temperature": 0,
            },
        }
    )


def _synthesis_request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "01J8ZK3W9P4Q5R6S7T8U9V0W1X",
            "job": "synthesis",
            "payload": {
                "state_vector": {"run_id": "r1", "regime": {"state": "risk_off"}},
                "sentiment": {"global_sentiment": -0.3},
            },
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SynthesisResponse",
                "max_tokens": 1024,
                "temperature": 0,
            },
        }
    )


def _monotonic_pair(elapsed_ms: int) -> Any:
    """A monotonic-ms reader that advances by ``elapsed_ms`` between the pre/post-call reads, so the
    TimeoutPolicy measures a deterministic latency (M4.3 measures elapsed = end - start)."""
    ticks = iter([1000, 1000 + elapsed_ms])

    def _read() -> int:
        try:
            return next(ticks)
        except StopIteration:  # pragma: no cover - only if called more than twice
            return 1000 + elapsed_ms

    return _read


def _gateway(adapter: _FakeAdapter, sink: list[CallRecord]) -> LLMGateway:
    return LLMGateway(
        registry=_registry(),
        prompt_builder=PromptBuilder(PROMPTS),
        validator=StructuredOutputValidator(INTERNAL_SCHEMAS),
        adapters={adapter.name: adapter},
        recorder=sink.append,
        clock=lambda: datetime(2026, 7, 14, 12, 46, 58, tzinfo=timezone.utc),
        monotonic_ms=_monotonic_pair(842),
    )


def test_gateway_implements_port() -> None:
    adapter = _FakeAdapter("fake", "{}")
    gw = _gateway(adapter, [])
    assert isinstance(gw, MarketReasoner)


def test_successful_sentiment_returns_response_and_records() -> None:
    text = json.dumps({"per_asset_sentiment": {"BTC": -0.38}, "global_sentiment": -0.35})
    adapter = _FakeAdapter("fake", text)
    sink: list[CallRecord] = []
    gw = _gateway(adapter, sink)

    result = gw.analyze_sentiment(_sentiment_request())
    assert isinstance(result, SentimentResponse)
    assert result.per_asset_sentiment["BTC"] == -0.38
    assert adapter.calls == 1

    assert len(sink) == 1
    rec = sink[0]
    assert rec.outcome == "success"
    assert rec.provider == "fake"
    assert rec.model_id == "fake-1"
    assert rec.prompt_version == "sentiment/v3"
    assert rec.latency_ms == 842
    assert rec.response_hash is not None


def test_successful_synthesis_returns_response() -> None:
    text = json.dumps(
        {
            "per_asset": {
                "BTC": {
                    "human_summary_fa": "خلاصه",
                    "ordinal_drivers": [
                        {"name": "cpi", "weight_type": "ordinal", "level": "major"}
                    ],
                    "novelty_flags": [],
                    "data_gap_notes": [],
                }
            },
            "grounding_ok": True,
        }
    )
    sink: list[CallRecord] = []
    result = _gateway(_FakeAdapter("fake", text), sink).synthesize(_synthesis_request())
    assert isinstance(result, SynthesisResponse)
    assert "BTC" in result.per_asset
    assert sink[0].llm_job.value == "synthesis"
    assert sink[0].prompt_version == "synthesis/v1"


def test_synthesis_failure_degrades() -> None:
    # Adapters signal a call failure via ProviderCallError (the neutral adapter error contract);
    # the gateway turns it into an honest DegradedMarker, never a crash (ADR-011 DR-3).
    from market_state_engine.reasoning.errors import ProviderCallError

    adapter = _FakeAdapter("fake", "", raise_exc=ProviderCallError("vendor 500"))
    sink: list[CallRecord] = []
    result = _gateway(adapter, sink).synthesize(_synthesis_request())
    assert isinstance(result, DegradedMarker)
    assert result.job.value == "synthesis"
    assert sink[0].outcome == "error"


def test_call_record_validates_against_schema(make_validator: Any) -> None:
    text = json.dumps({"per_asset_sentiment": {"BTC": -0.1}, "global_sentiment": -0.1})
    sink: list[CallRecord] = []
    _gateway(_FakeAdapter("fake", text), sink).analyze_sentiment(_sentiment_request())
    validator = make_validator("call_record.v1.json")
    errors = list(validator.iter_errors(sink[0].to_contract_dict()))
    assert not errors


def test_malformed_output_degrades_honestly() -> None:
    adapter = _FakeAdapter("fake", "not json")
    sink: list[CallRecord] = []
    result = _gateway(adapter, sink).analyze_sentiment(_sentiment_request())
    assert isinstance(result, DegradedMarker)
    assert result.job is LlmJob.SENTIMENT
    assert result.last_attempt.provider == "fake"
    # A failure attempt is still recorded (frozen invariant #5), with a null response.
    assert len(sink) == 1
    assert sink[0].outcome == "error"
    assert sink[0].response is None


def test_no_adapter_bound_degrades() -> None:
    # Gateway with an empty adapter map (M4.1 default: no concrete adapters).
    gw = LLMGateway(
        registry=_registry(),
        prompt_builder=PromptBuilder(PROMPTS),
        validator=StructuredOutputValidator(INTERNAL_SCHEMAS),
        adapters={},
        recorder=None,
        clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    result = gw.analyze_sentiment(_sentiment_request())
    assert isinstance(result, DegradedMarker)


def test_no_enabled_providers_degrades() -> None:
    reg = ProviderRegistry.from_mapping(
        {
            "version": "1.0.0",
            "routing": {"strategy": "priority", "degrade_after_all_fail": True},
            "defaults": {"temperature": 0, "max_tokens": 512, "timeout_seconds": 20, "retries": 2},
            "providers": [
                {
                    "name": "fake",
                    "enabled": False,
                    "priority": 1,
                    "api_key_env": "FAKE_KEY",
                    "models": {"sentiment": "fake-1", "synthesis": "fake-1"},
                }
            ],
        }
    )
    gw = LLMGateway(
        registry=reg,
        prompt_builder=PromptBuilder(PROMPTS),
        validator=StructuredOutputValidator(INTERNAL_SCHEMAS),
        adapters={},
        clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    result = gw.analyze_sentiment(_sentiment_request())
    assert isinstance(result, DegradedMarker)
    assert result.last_attempt.provider == "none"
