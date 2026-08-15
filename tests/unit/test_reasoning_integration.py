"""M4.5 Final Integration & Degraded Run — end-to-end reasoning flow through the facade.

Wires a full ``MarketReasoner`` from the real config dirs (providers.yaml / pricing / prompts /
schemas) via ``build_gateway`` and ``build_replay_gateway``, with offline provider doubles injected
— no network, no vendor SDK. Verifies the end-to-end flow, the ADR-011 Degraded Run, replay
reproduction through the facade, provider independence, and deterministic-core isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from market_state_engine.reasoning import (
    DegradedMarker,
    MarketReasoner,
    ReasoningPaths,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
    build_gateway,
    build_replay_gateway,
)
from market_state_engine.reasoning.adapters.fake import FakeProvider
from market_state_engine.reasoning.errors import ProviderCallError
from market_state_engine.reasoning.models import CallRecord
from market_state_engine.reasoning.replay import verify_replay
from market_state_engine.reasoning.types import RawProviderResult

REPO = Path(__file__).resolve().parents[2]


def _paths() -> ReasoningPaths:
    return ReasoningPaths(REPO)


def _clock() -> datetime:
    return datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _sentiment_request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "run-e2e-1",
            "job": "sentiment",
            "payload": {
                "assets": ["BTC", "ETH"],
                "news_digest": {"run_id": "run-e2e-1", "items": []},
            },
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
            "run_id": "run-e2e-1",
            "job": "synthesis",
            "payload": {
                "state_vector": {"run_id": "run-e2e-1", "regime": {"state": "risk_off"}},
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


def _sentiment_text() -> str:
    return json.dumps(
        {"per_asset_sentiment": {"BTC": -0.38, "ETH": -0.41}, "global_sentiment": -0.35}
    )


def _synthesis_text() -> str:
    return json.dumps(
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


def _fake(name: str, text: str) -> FakeProvider:
    return FakeProvider(
        name=name,
        result=RawProviderResult(
            text=text, input_tokens=600, output_tokens=70, finish_reason="stop"
        ),
    )


# --- End-to-end reasoning flow -------------------------------------------------------
def test_build_gateway_end_to_end_sentiment() -> None:
    # Anthropic is the enabled provider in providers.yaml; inject a canned offline double.
    sink: list[CallRecord] = []
    ticks = iter([1000, 1250])  # injected monotonic advances 250ms across the call
    gw = build_gateway(
        _paths(),
        overrides={"anthropic": _fake("anthropic", _sentiment_text())},
        recorder=sink.append,
        clock=_clock,
        monotonic_ms=lambda: next(ticks, 1250),
    )
    assert isinstance(gw, MarketReasoner)
    result = gw.analyze_sentiment(_sentiment_request())
    assert isinstance(result, SentimentResponse)
    assert result.per_asset_sentiment["BTC"] == -0.38
    # A Call Record was captured, with a versioned cost from the real pricing table.
    assert sink[-1].outcome == "success"
    assert sink[-1].provider == "anthropic"
    assert sink[-1].estimated_cost is not None
    assert sink[-1].latency_ms == 250
    assert sink[-1].model_id == "claude-sonnet-5"  # from the frozen providers.yaml


def test_build_gateway_end_to_end_synthesis() -> None:
    gw = build_gateway(
        _paths(), overrides={"anthropic": _fake("anthropic", _synthesis_text())}, clock=_clock
    )
    result = gw.synthesize(_synthesis_request())
    assert isinstance(result, SynthesisResponse)
    assert "BTC" in result.per_asset


def test_gateway_serves_configured_anthropic_provider() -> None:
    # Only Anthropic is enabled in the current provider configuration.
    sink: list[CallRecord] = []
    gw = build_gateway(
        _paths(),
        overrides={"anthropic": _fake("anthropic", _sentiment_text())},
        recorder=sink.append,
        clock=_clock,
    )
    result = gw.analyze_sentiment(_sentiment_request())
    assert isinstance(result, SentimentResponse)
    assert sink[-1].provider == "anthropic"
    assert sink[-1].model_id == "claude-sonnet-5"


# --- ADR-011 Degraded Run ------------------------------------------------------------
def test_all_providers_fail_yields_degraded_marker() -> None:
    sink: list[CallRecord] = []
    gw = build_gateway(
        _paths(),
        overrides={
            "anthropic": FakeProvider(name="anthropic", raise_exc=ProviderCallError("down"))
        },
        recorder=sink.append,
        clock=_clock,
    )
    result = gw.analyze_sentiment(_sentiment_request())
    # Never raises, never fabricates: honest DegradedMarker (ADR-011 DR-2/DR-3).
    assert isinstance(result, DegradedMarker)
    assert result.job.value == "sentiment"
    assert result.last_attempt.provider == "anthropic"
    # Every attempt is still recorded (frozen invariant #5).
    assert sink
    assert all(r.outcome == "error" for r in sink)


def test_partial_degradation_is_per_job() -> None:
    # Sentiment succeeds, synthesis degrades — per-LLM-job degradation (ADR-011 DR-5).
    good = build_gateway(
        _paths(), overrides={"anthropic": _fake("anthropic", _sentiment_text())}, clock=_clock
    )
    sentiment = good.analyze_sentiment(_sentiment_request())
    assert isinstance(sentiment, SentimentResponse)

    bad = build_gateway(
        _paths(),
        overrides={"anthropic": FakeProvider(name="anthropic", raise_exc=ProviderCallError("y"))},
        clock=_clock,
    )
    synthesis = bad.synthesize(_synthesis_request())
    assert isinstance(synthesis, DegradedMarker)


# --- Replay compatibility through the facade -----------------------------------------
def test_replay_gateway_reproduces_recorded_run() -> None:
    # 1) Live run through the facade, recording Call Records.
    live_sink: list[CallRecord] = []
    live = build_gateway(
        _paths(),
        overrides={"anthropic": _fake("anthropic", _sentiment_text())},
        recorder=live_sink.append,
        clock=_clock,
    )
    live_result = live.analyze_sentiment(_sentiment_request())
    assert isinstance(live_result, SentimentResponse)

    # 2) Replay run through the facade — no live provider, adapters from records.
    replay_sink: list[CallRecord] = []
    replay = build_replay_gateway(_paths(), live_sink, recorder=replay_sink.append, clock=_clock)
    replay_result = replay.analyze_sentiment(_sentiment_request())
    assert isinstance(replay_result, SentimentResponse)

    # 3) Byte-identical on the replay-critical fields.
    assert verify_replay(live_sink, replay_sink).matched
    assert live_result.model_dump() == replay_result.model_dump()


# --- Provider independence / deterministic-core isolation ----------------------------
def test_public_surface_names_no_vendor() -> None:
    import market_state_engine.reasoning as reasoning

    for name in reasoning.__all__:
        assert "openai" not in name.lower()
        assert "claude" not in name.lower()
        assert "anthropic" not in name.lower()
        assert "gemini" not in name.lower()


def test_core_does_not_import_reasoning() -> None:
    # Structural guard mirrored from the import-boundary suite: the deterministic core never imports
    # the reasoning layer (ADR-007 D-1). Verified here as part of the integration story too.
    import importlib
    import pkgutil

    import market_state_engine.core as core_pkg

    offenders: list[str] = []
    for mod in pkgutil.walk_packages(core_pkg.__path__, prefix="market_state_engine.core."):
        module = importlib.import_module(mod.name)
        for attr in vars(module).values():
            mod_name = getattr(attr, "__module__", "")
            if isinstance(mod_name, str) and mod_name.startswith("market_state_engine.reasoning"):
                offenders.append(f"{mod.name} -> {mod_name}")
    assert not offenders, offenders
