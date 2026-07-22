"""Integration facade — assemble a fully-wired ``MarketReasoner`` from configuration (M4.5).

This is the single composition point that ties the frozen M4 components together, with **no new
behaviour and no redesign**: it constructs the ``ProviderRegistry`` (from ``providers.yaml``), the
``PromptBuilder`` (from ``prompts/``), the ``StructuredOutputValidator`` (from
``schemas/internal/``), the ``PriceTable`` (from ``pricing.vN.yaml``), builds the provider adapters,
and returns an ``LLMGateway`` — the production ``MarketReasoner``.

Two modes, same boundary:
  - ``build_gateway``        — live/dev wiring. Adapters come from the config-driven factory; inject
                               ``overrides`` (e.g. a ``FakeProvider``) for offline dev/tests.
  - ``build_replay_gateway`` — replay wiring (ADR-004 / frozen invariant #6). Adapters are
                               ``ReplayProvider``s built from recorded Call Records; no live
                               provider is ever contacted. The Gateway drives them identically.

The deterministic core still sees only the ``MarketReasoner`` port; this facade lives wholly in the
reasoning layer. Time/recorder are injectable so the whole flow stays deterministic and replay-safe.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from .adapters.base import ProviderAdapter
from .adapters.factory import build_adapters
from .gateway import CallRecorder, Clock, LLMGateway, MonotonicMs
from .models import CallRecord
from .pricing import PriceTable
from .prompt_builder import PromptBuilder
from .registry import ProviderRegistry
from .replay import build_replay_adapters
from .structured_output import StructuredOutputValidator

# Standard locations relative to a project root (canonical repo layout, master-prompt §10).
_PROVIDERS_REL = Path("config") / "models" / "providers.yaml"
_PRICING_REL = Path("config") / "models" / "pricing.v1.yaml"
_PROMPTS_REL = Path("prompts")
_SCHEMAS_REL = Path("schemas") / "internal"


class ReasoningPaths:
    """Resolved config/artifact locations for wiring the reasoning layer from a project root."""

    def __init__(
        self,
        root: Path,
        *,
        providers: Path | None = None,
        pricing: Path | None = None,
        prompts: Path | None = None,
        schemas_internal: Path | None = None,
    ) -> None:
        self.providers = providers or root / _PROVIDERS_REL
        self.pricing = pricing or root / _PRICING_REL
        self.prompts = prompts or root / _PROMPTS_REL
        self.schemas_internal = schemas_internal or root / _SCHEMAS_REL


def _components(
    paths: ReasoningPaths,
) -> tuple[ProviderRegistry, PromptBuilder, StructuredOutputValidator, PriceTable]:
    registry = ProviderRegistry.from_file(paths.providers)
    prompt_builder = PromptBuilder(paths.prompts)
    validator = StructuredOutputValidator(paths.schemas_internal)
    price_table = PriceTable.from_file(paths.pricing)
    return registry, prompt_builder, validator, price_table


def build_gateway(
    paths: ReasoningPaths,
    *,
    overrides: Mapping[str, ProviderAdapter] | None = None,
    recorder: CallRecorder | None = None,
    clock: Clock | None = None,
    monotonic_ms: MonotonicMs | None = None,
) -> LLMGateway:
    """Wire a live ``LLMGateway`` from config. ``overrides`` inject offline doubles per provider."""
    registry, prompt_builder, validator, price_table = _components(paths)
    adapters = build_adapters(registry, overrides=overrides)
    return _assemble(
        registry, prompt_builder, validator, price_table, adapters, recorder, clock, monotonic_ms
    )


def build_replay_gateway(
    paths: ReasoningPaths,
    records: Iterable[CallRecord],
    *,
    recorder: CallRecorder | None = None,
    clock: Clock | None = None,
    monotonic_ms: MonotonicMs | None = None,
) -> LLMGateway:
    """Wire a replay ``LLMGateway``: adapters are ReplayProviders over recorded Call Records.

    No live provider is contacted; the same request reproduces the recorded run (invariant #6).
    """
    registry, prompt_builder, validator, price_table = _components(paths)
    adapters: dict[str, ProviderAdapter] = dict(build_replay_adapters(records))
    return _assemble(
        registry, prompt_builder, validator, price_table, adapters, recorder, clock, monotonic_ms
    )


def _assemble(
    registry: ProviderRegistry,
    prompt_builder: PromptBuilder,
    validator: StructuredOutputValidator,
    price_table: PriceTable,
    adapters: Mapping[str, ProviderAdapter],
    recorder: CallRecorder | None,
    clock: Clock | None,
    monotonic_ms: MonotonicMs | None,
) -> LLMGateway:
    kwargs: dict[str, object] = {
        "registry": registry,
        "prompt_builder": prompt_builder,
        "validator": validator,
        "adapters": adapters,
        "recorder": recorder,
        "price_table": price_table,
    }
    if clock is not None:
        kwargs["clock"] = clock
    if monotonic_ms is not None:
        kwargs["monotonic_ms"] = monotonic_ms
    return LLMGateway(**kwargs)  # type: ignore[arg-type]


__all__ = [
    "ReasoningPaths",
    "build_gateway",
    "build_replay_gateway",
]
