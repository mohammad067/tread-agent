"""ProviderRegistry + provider config loading (M4.1). Config-driven, fail-fast, no secrets."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_state_engine.reasoning.errors import ProviderConfigError
from market_state_engine.reasoning.registry import ProviderRegistry

REPO = Path(__file__).resolve().parents[2]
PROVIDERS_YAML = REPO / "config" / "models" / "providers.yaml"


def _base_config() -> dict[str, object]:
    return {
        "version": "1.0.0",
        "routing": {"strategy": "priority", "degrade_after_all_fail": True},
        "defaults": {"temperature": 0, "max_tokens": 1024, "timeout_seconds": 20, "retries": 2},
        "providers": [
            {
                "name": "openai",
                "enabled": True,
                "priority": 1,
                "weight": 60,
                "api_key_env": "OPENAI_API_KEY",
                "models": {"sentiment": "gpt-5.5", "synthesis": "gpt-5.5"},
            },
            {
                "name": "anthropic",
                "enabled": False,
                "priority": 2,
                "weight": 40,
                "api_key_env": "ANTHROPIC_API_KEY",
                "models": {"sentiment": "claude-sonnet-5", "synthesis": "claude-sonnet-5"},
            },
        ],
    }


def test_loads_frozen_providers_file() -> None:
    reg = ProviderRegistry.from_file(PROVIDERS_YAML)
    assert reg.version == "1.0.0"
    assert reg.strategy == "priority"
    # gemini is enabled: false in the frozen file → excluded from the routing set.
    names = [p.name for p in reg.enabled_providers()]
    assert names == ["openai", "anthropic"]


def test_enabled_providers_sorted_by_priority() -> None:
    reg = ProviderRegistry.from_mapping(_base_config())
    enabled = reg.enabled_providers()
    assert [p.name for p in enabled] == ["openai"]  # anthropic disabled


def test_call_params_resolve_override_else_default() -> None:
    reg = ProviderRegistry.from_mapping(_base_config())
    openai = reg.get("openai")
    params = reg.call_params_for(openai, "sentiment")
    assert params.model_id == "gpt-5.5"
    assert params.max_tokens == 1024  # from defaults
    assert params.temperature == 0.0
    assert params.timeout_seconds == 20


def test_missing_file_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_file(tmp_path / "nope.yaml")


def test_degrade_after_all_fail_must_stay_true() -> None:
    cfg = _base_config()
    cfg["routing"] = {"strategy": "priority", "degrade_after_all_fail": False}
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_mapping(cfg)


def test_duplicate_provider_names_rejected() -> None:
    cfg = _base_config()
    providers = cfg["providers"]
    assert isinstance(providers, list)
    providers.append(dict(providers[0]))  # duplicate 'openai'
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_mapping(cfg)


def test_unknown_provider_lookup_raises() -> None:
    reg = ProviderRegistry.from_mapping(_base_config())
    with pytest.raises(ProviderConfigError):
        reg.get("mistral")


def test_invalid_strategy_rejected() -> None:
    cfg = _base_config()
    cfg["routing"] = {"strategy": "round_robin", "degrade_after_all_fail": True}
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_mapping(cfg)


def test_weighted_strategy_accepted() -> None:
    cfg = _base_config()
    cfg["routing"] = {"strategy": "weighted", "degrade_after_all_fail": True}
    reg = ProviderRegistry.from_mapping(cfg)
    assert reg.strategy == "weighted"


def test_provider_override_params_take_precedence() -> None:
    cfg = _base_config()
    providers = cfg["providers"]
    assert isinstance(providers, list)
    providers[0]["max_tokens"] = 256
    providers[0]["temperature"] = 0.2
    providers[0]["timeout_seconds"] = 5
    reg = ProviderRegistry.from_mapping(cfg)
    params = reg.call_params_for(reg.get("openai"), "synthesis")
    assert params.max_tokens == 256
    assert params.temperature == 0.2
    assert params.timeout_seconds == 5


def test_unknown_job_rejected() -> None:
    reg = ProviderRegistry.from_mapping(_base_config())
    with pytest.raises(ProviderConfigError):
        reg.config.model_for(reg.get("openai"), "novelty")


def test_empty_providers_list_rejected() -> None:
    cfg = _base_config()
    cfg["providers"] = []
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_mapping(cfg)


def test_non_mapping_config_rejected() -> None:
    with pytest.raises(ProviderConfigError):
        ProviderRegistry.from_mapping(["not", "a", "mapping"])
