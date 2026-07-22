"""``ProviderRegistry`` — load enabled providers + policies from ``providers.yaml`` and expose the
routing set (llm-provider-architecture §2 / module-catalog B3).

Loads and validates the config at startup (fail-fast — a malformed file raises
``ProviderConfigError`` here, never mid-run), holds no secrets, and hardcodes no provider. The
registry exposes the *config* only; the effective ``CallParams`` for a job are resolved via
``call_params_for`` (provider override falling back to defaults). Health/circuit gating and adapter
binding arrive in M4.2 — the registry here is a pure, read-only view over configuration.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .errors import ProviderConfigError
from .provider_config import ProviderCfg, ProvidersConfig
from .types import CallParams


class ProviderRegistry:
    def __init__(self, config: ProvidersConfig) -> None:
        self._config = config

    # --- construction -----------------------------------------------------------------
    @classmethod
    def from_file(cls, path: Path) -> ProviderRegistry:
        if not path.is_file():
            raise ProviderConfigError(f"providers config not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise ProviderConfigError(f"invalid YAML in {path}: {exc}") from exc
        return cls.from_mapping(data, source=str(path))

    @classmethod
    def from_mapping(cls, data: object, source: str = "<mapping>") -> ProviderRegistry:
        if not isinstance(data, dict):
            raise ProviderConfigError(f"providers config {source} must be a mapping")
        try:
            config = ProvidersConfig(**data)
        except ValidationError as exc:
            raise ProviderConfigError(f"providers config invalid ({source}): {exc}") from exc
        return cls(config)

    # --- read-only views ---------------------------------------------------------------
    @property
    def version(self) -> str:
        return self._config.version

    @property
    def config(self) -> ProvidersConfig:
        return self._config

    @property
    def strategy(self) -> str:
        return self._config.routing.strategy

    def enabled_providers(self) -> list[ProviderCfg]:
        """Enabled providers in ascending priority order — the failover chain order (ADR-011 DR-1).

        Ties broken by name for a deterministic, replay-stable ordering.
        """
        enabled = [p for p in self._config.providers if p.enabled]
        return sorted(enabled, key=lambda p: (p.priority, p.name))

    def get(self, name: str) -> ProviderCfg:
        for provider in self._config.providers:
            if provider.name == name:
                return provider
        raise ProviderConfigError(f"unknown provider: {name!r}")

    # --- effective call parameters -----------------------------------------------------
    def call_params_for(self, provider: ProviderCfg, job: str) -> CallParams:
        """Resolve a provider's effective ``CallParams`` (provider override else defaults)."""
        defaults = self._config.defaults
        return CallParams(
            model_id=self._config.model_for(provider, job),
            max_tokens=provider.max_tokens or defaults.max_tokens,
            temperature=(
                provider.temperature if provider.temperature is not None else defaults.temperature
            ),
            timeout_seconds=provider.timeout_seconds or defaults.timeout_seconds,
        )
