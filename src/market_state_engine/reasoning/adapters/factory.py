"""Provider registration + initialization: build adapter instances from configuration.

A single registration table maps a config provider ``name`` to its adapter class. ``build_adapters``
reads the enabled providers from a ``ProviderRegistry`` and instantiates one adapter each, ready to
hand to the ``LLMGateway`` (which does the per-call selection). Adding a vendor = one adapter module
+ one table entry + one config block — nothing else changes (frozen invariant #3).

Selection is config-driven only: a provider absent from ``providers.yaml`` or disabled there is
never instantiated. Test doubles inject via ``overrides`` so CI wires end-to-end without any SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ..errors import ProviderConfigError
from ..provider_config import ProviderCfg
from ..registry import ProviderRegistry
from .base import ProviderAdapter
from .claude_provider import ClaudeProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider


class _AdapterBuilder(Protocol):
    def __call__(self, provider: ProviderCfg) -> ProviderAdapter: ...


# Registration table: config provider name -> how to construct its adapter. The ONLY place vendor
# adapter classes are wired to config names.
_REGISTRATION: dict[str, _AdapterBuilder] = {
    "openai": lambda p: OpenAIProvider(p.name, p.api_key_env),
    "anthropic": lambda p: ClaudeProvider(p.name, p.api_key_env),
    "gemini": lambda p: GeminiProvider(p.name, p.api_key_env),
}


def registered_providers() -> frozenset[str]:
    """Config names that have a bound adapter class."""
    return frozenset(_REGISTRATION)


def build_adapter(provider: ProviderCfg) -> ProviderAdapter:
    """Instantiate the adapter for one configured provider (fail-fast on an unknown name)."""
    builder = _REGISTRATION.get(provider.name)
    if builder is None:
        raise ProviderConfigError(
            f"provider {provider.name!r} has no registered adapter (known: {sorted(_REGISTRATION)})"
        )
    return builder(provider)


def build_adapters(
    registry: ProviderRegistry,
    overrides: Mapping[str, ProviderAdapter] | None = None,
) -> dict[str, ProviderAdapter]:
    """Build the adapter map for every enabled provider in the registry.

    ``overrides`` (a name -> adapter map) replaces the built adapter for that name — the offline
    seam for injecting ``FakeProvider`` / a stubbed client in tests, without touching production.
    """
    overrides = overrides or {}
    adapters: dict[str, ProviderAdapter] = {}
    for provider in registry.enabled_providers():
        if provider.name in overrides:
            adapters[provider.name] = overrides[provider.name]
        else:
            adapters[provider.name] = build_adapter(provider)
    return adapters
