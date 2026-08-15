"""Provider registration + selection tests (M4.2): config-driven, end-to-end through the gateway."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from market_state_engine.reasoning.adapters.claude_provider import ClaudeProvider
from market_state_engine.reasoning.adapters.factory import (
    build_adapter,
    build_adapters,
    registered_providers,
)
from market_state_engine.reasoning.adapters.fake import FakeProvider
from market_state_engine.reasoning.adapters.openai_provider import OpenAIProvider
from market_state_engine.reasoning.errors import ProviderConfigError
from market_state_engine.reasoning.gateway import LLMGateway
from market_state_engine.reasoning.models import ReasoningRequest, SentimentResponse
from market_state_engine.reasoning.prompt_builder import PromptBuilder
from market_state_engine.reasoning.registry import ProviderRegistry
from market_state_engine.reasoning.structured_output import StructuredOutputValidator

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "prompts"
INTERNAL_SCHEMAS = REPO / "schemas" / "internal"
PROVIDERS_YAML = REPO / "config" / "models" / "providers.yaml"


def test_registered_names_cover_frozen_config() -> None:
    assert registered_providers() == {"openai", "anthropic", "gemini"}


def test_build_adapter_by_name() -> None:
    reg = ProviderRegistry.from_file(PROVIDERS_YAML)
    assert isinstance(build_adapter(reg.get("openai")), OpenAIProvider)
    assert isinstance(build_adapter(reg.get("anthropic")), ClaudeProvider)


def test_build_adapters_only_enabled() -> None:
    # gemini is enabled:false in the frozen file → not instantiated (config-driven selection).
    reg = ProviderRegistry.from_file(PROVIDERS_YAML)
    adapters = build_adapters(reg)
    assert set(adapters) == {"anthropic"}
    assert adapters["anthropic"].name == "anthropic"


def test_build_adapters_override_injects_double() -> None:
    reg = ProviderRegistry.from_file(PROVIDERS_YAML)
    fake = FakeProvider(name="anthropic", text="{}")
    adapters = build_adapters(reg, overrides={"anthropic": fake})
    assert adapters["anthropic"] is fake


def test_unknown_provider_has_no_adapter() -> None:
    reg = ProviderRegistry.from_mapping(
        {
            "version": "1.0.0",
            "routing": {"strategy": "priority", "degrade_after_all_fail": True},
            "defaults": {"temperature": 0, "max_tokens": 8, "timeout_seconds": 5, "retries": 0},
            "providers": [
                {
                    "name": "mistral",
                    "enabled": True,
                    "priority": 1,
                    "api_key_env": "MISTRAL_KEY",
                    "models": {"sentiment": "m", "synthesis": "m"},
                }
            ],
        }
    )
    with pytest.raises(ProviderConfigError):
        build_adapters(reg)


def test_selection_picks_highest_priority_through_gateway() -> None:
    # Two enabled providers; the gateway (M4.1 single-pick) selects priority 1. We inject fakes for
    # both and assert only the priority-1 one is called — pure config-driven selection.
    reg = ProviderRegistry.from_mapping(
        {
            "version": "1.0.0",
            "routing": {"strategy": "priority", "degrade_after_all_fail": True},
            "defaults": {"temperature": 0, "max_tokens": 64, "timeout_seconds": 5, "retries": 0},
            "providers": [
                {
                    "name": "openai",
                    "enabled": True,
                    "priority": 1,
                    "api_key_env": "OPENAI_API_KEY",
                    "models": {"sentiment": "gpt", "synthesis": "gpt"},
                },
                {
                    "name": "anthropic",
                    "enabled": True,
                    "priority": 2,
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "models": {"sentiment": "claude", "synthesis": "claude"},
                },
            ],
        }
    )
    text = json.dumps({"per_asset_sentiment": {"BTC": 0.1}, "global_sentiment": 0.1})
    primary = FakeProvider(name="openai", text=text)
    secondary = FakeProvider(name="anthropic", text=text)
    gw = LLMGateway(
        registry=reg,
        prompt_builder=PromptBuilder(PROMPTS),
        validator=StructuredOutputValidator(INTERNAL_SCHEMAS),
        adapters=build_adapters(reg, overrides={"openai": primary, "anthropic": secondary}),
        clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    request = ReasoningRequest.model_validate(
        {
            "run_id": "r1",
            "job": "sentiment",
            "payload": {"assets": ["BTC"], "news_digest": {"run_id": "r1", "items": []}},
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SentimentResponse",
                "max_tokens": 64,
                "temperature": 0,
            },
        }
    )
    result = gw.analyze_sentiment(request)
    assert isinstance(result, SentimentResponse)
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 0  # lower priority never touched (no failover in this batch)
    # The selected provider's configured model reached the adapter.
    assert primary.calls[0][1].model_id == "gpt"
