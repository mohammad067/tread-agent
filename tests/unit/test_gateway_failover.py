"""Gateway failover/reliability integration tests (M4.3): the full ADR-011 chain end-to-end.

Exercises retry → timeout → next-provider failover → circuit breaker → Degraded Run, all through the
public ``MarketReasoner`` port with injected time and scriptable in-test adapters. Offline only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from market_state_engine.reasoning.errors import ProviderCallError
from market_state_engine.reasoning.gateway import LLMGateway
from market_state_engine.reasoning.models import (
    CallRecord,
    DegradedMarker,
    ReasoningRequest,
    SentimentResponse,
)
from market_state_engine.reasoning.prompt_builder import PromptBuilder
from market_state_engine.reasoning.registry import ProviderRegistry
from market_state_engine.reasoning.structured_output import StructuredOutputValidator
from market_state_engine.reasoning.types import CallParams, RawProviderResult, RenderedPrompt

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "prompts"
INTERNAL_SCHEMAS = REPO / "schemas" / "internal"

GOOD = json.dumps({"per_asset_sentiment": {"BTC": -0.2}, "global_sentiment": -0.2})


class _ScriptAdapter:
    """Provider double that replays a scripted sequence of outcomes across successive calls."""

    def __init__(self, name: str, script: list[object], *, elapsed_ms: int = 10) -> None:
        self._name = name
        self._script = list(script)
        self._elapsed_ms = elapsed_ms
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        step = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return RawProviderResult(text=str(step), finish_reason="stop")


def _registry(providers: list[dict[str, object]], strategy: str = "priority") -> ProviderRegistry:
    return ProviderRegistry.from_mapping(
        {
            "version": "1.0.0",
            "routing": {"strategy": strategy, "degrade_after_all_fail": True},
            "defaults": {
                "temperature": 0,
                "max_tokens": 512,
                "timeout_seconds": 20,
                "retries": 1,
                "backoff": {"type": "exponential", "base_ms": 1, "max_ms": 2},
                "circuit_breaker": {
                    "failure_threshold": 2,
                    "window_seconds": 120,
                    "half_open_after_seconds": 60,
                },
            },
            "providers": providers,
        }
    )


def _p(name: str, priority: int, **extra: object) -> dict[str, object]:
    return {
        "name": name,
        "enabled": True,
        "priority": priority,
        "api_key_env": f"{name.upper()}_KEY",
        "models": {"sentiment": f"{name}-m", "synthesis": f"{name}-m"},
        **extra,
    }


def _request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "run-xyz",
            "job": "sentiment",
            "payload": {"assets": ["BTC"], "news_digest": {"run_id": "run-xyz", "items": []}},
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SentimentResponse",
                "max_tokens": 512,
                "temperature": 0,
            },
        }
    )


def _make_gateway(
    registry: ProviderRegistry,
    adapters: dict[str, _ScriptAdapter],
    sink: list[CallRecord],
    now_s: list[float] | None = None,
    monotonic_ms: object | None = None,
) -> LLMGateway:
    now_s = now_s if now_s is not None else [0.0]
    return LLMGateway(
        registry=registry,
        prompt_builder=PromptBuilder(PROMPTS),
        validator=StructuredOutputValidator(INTERNAL_SCHEMAS),
        adapters=adapters,  # type: ignore[arg-type]
        recorder=sink.append,
        clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        monotonic_ms=monotonic_ms if monotonic_ms is not None else (lambda: 0),  # type: ignore[arg-type]
        monotonic_s=lambda: now_s[0],
        sleep=lambda _s: None,
    )


# --- Retry (via the gateway) ---------------------------------------------------------
def test_gateway_retries_then_succeeds_same_provider() -> None:
    adapter = _ScriptAdapter("openai", [ProviderCallError("blip"), GOOD])
    sink: list[CallRecord] = []
    gw = _make_gateway(_registry([_p("openai", 1)]), {"openai": adapter}, sink)
    result = gw.analyze_sentiment(_request())
    assert isinstance(result, SentimentResponse)
    assert adapter.calls == 2  # one retry
    assert sink[-1].outcome == "success"
    assert sink[-1].retries == 1  # recorded retry count


# --- Failover across providers -------------------------------------------------------
def test_gateway_fails_over_to_next_provider() -> None:
    a = _ScriptAdapter("openai", [ProviderCallError("down"), ProviderCallError("down")])
    b = _ScriptAdapter("anthropic", [GOOD])
    sink: list[CallRecord] = []
    gw = _make_gateway(
        _registry([_p("openai", 1), _p("anthropic", 2)]),
        {"openai": a, "anthropic": b},
        sink,
    )
    result = gw.analyze_sentiment(_request())
    assert isinstance(result, SentimentResponse)
    assert a.calls == 2  # exhausted its retries
    assert b.calls == 1  # failover landed here
    # Two records: openai attempt_index 0 (error), anthropic attempt_index 1 (success).
    assert [r.outcome for r in sink] == ["error", "success"]
    assert sink[1].attempt_index == 1
    assert sink[1].provider == "anthropic"


def test_gateway_all_providers_fail_degrades() -> None:
    a = _ScriptAdapter("openai", [ProviderCallError("x")])
    b = _ScriptAdapter("anthropic", [ProviderCallError("y")])
    sink: list[CallRecord] = []
    gw = _make_gateway(
        _registry([_p("openai", 1), _p("anthropic", 2)]),
        {"openai": a, "anthropic": b},
        sink,
    )
    result = gw.analyze_sentiment(_request())
    assert isinstance(result, DegradedMarker)
    assert result.last_attempt.provider == "anthropic"  # last one tried
    # Every attempt is recorded (frozen invariant #5), all failures.
    assert all(r.outcome == "error" for r in sink)


# --- Timeout leads to failover -------------------------------------------------------
def test_gateway_timeout_fails_over() -> None:
    # openai "takes" 30s (> 20s deadline) each attempt via the ms clock; anthropic is fast.
    a = _ScriptAdapter("openai", [GOOD, GOOD])
    b = _ScriptAdapter("anthropic", [GOOD])
    sink: list[CallRecord] = []
    # ms clock: openai reads produce large elapsed; anthropic small. We advance a shared counter.
    ticks = iter([0, 30_000, 30_000, 60_000, 60_000, 60_010])

    def ms() -> int:
        try:
            return next(ticks)
        except StopIteration:  # pragma: no cover
            return 60_010

    gw = _make_gateway(
        _registry([_p("openai", 1), _p("anthropic", 2)]),
        {"openai": a, "anthropic": b},
        sink,
        monotonic_ms=ms,
    )
    result = gw.analyze_sentiment(_request())
    assert isinstance(result, SentimentResponse)
    assert sink[0].outcome == "timeout"
    assert sink[0].provider == "openai"
    assert sink[-1].outcome == "success"
    assert sink[-1].provider == "anthropic"


# --- Circuit breaker across runs -----------------------------------------------------
def test_gateway_circuit_opens_and_skips_provider() -> None:
    # openai always fails. The breaker records one provider-level failure per run; with
    # failure_threshold=2 it opens after two failing runs, then the provider is skipped.
    a = _ScriptAdapter("openai", [ProviderCallError("perma")])
    b = _ScriptAdapter("anthropic", [GOOD])
    sink: list[CallRecord] = []
    gw = _make_gateway(
        _registry([_p("openai", 1), _p("anthropic", 2)]),
        {"openai": a, "anthropic": b},
        sink,
    )
    # Runs 1 & 2: openai fails each time (anthropic serves), breaker opens at the end of run 2.
    assert isinstance(gw.analyze_sentiment(_request()), SentimentResponse)
    assert isinstance(gw.analyze_sentiment(_request()), SentimentResponse)
    openai_calls_after_open = a.calls
    sink.clear()
    # Run 3: openai's circuit is open → skipped without an adapter call.
    assert isinstance(gw.analyze_sentiment(_request()), SentimentResponse)
    assert a.calls == openai_calls_after_open  # no further openai calls
    assert sink[0].outcome == "circuit_open"
    assert sink[0].provider == "openai"
    assert sink[-1].provider == "anthropic"


# --- Health monitor (operational only) -----------------------------------------------
def test_gateway_updates_health_snapshot() -> None:
    a = _ScriptAdapter("openai", [ProviderCallError("x"), ProviderCallError("x")])
    b = _ScriptAdapter("anthropic", [GOOD])
    sink: list[CallRecord] = []
    gw = _make_gateway(
        _registry([_p("openai", 1), _p("anthropic", 2)]),
        {"openai": a, "anthropic": b},
        sink,
    )
    gw.analyze_sentiment(_request())
    assert gw.health.snapshot("anthropic").success_rate == 1.0
    assert gw.health.snapshot("openai").failures >= 1


# --- Weighted routing through the gateway --------------------------------------------
def test_gateway_weighted_routing_is_replay_stable() -> None:
    reg = _registry(
        [_p("openai", 1, weight=10), _p("anthropic", 2, weight=90)], strategy="weighted"
    )
    a = _ScriptAdapter("openai", [GOOD, GOOD])
    b = _ScriptAdapter("anthropic", [GOOD, GOOD])
    sink: list[CallRecord] = []
    gw = _make_gateway(reg, {"openai": a, "anthropic": b}, sink)
    # Same run_id → same provider chosen first, twice.
    gw.analyze_sentiment(_request())
    r1 = sink[0].provider
    sink.clear()
    gw2 = _make_gateway(
        reg,
        {
            "openai": _ScriptAdapter("openai", [GOOD]),
            "anthropic": _ScriptAdapter("anthropic", [GOOD]),
        },
        sink,
    )
    gw2.analyze_sentiment(_request())
    assert sink[0].provider == r1  # deterministic weighted pick
