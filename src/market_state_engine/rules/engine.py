"""RuleEngine facade: match active rules against event features, resolve guards + conflicts, and
emit per-asset RuleActivations and CausalLinks. Pure.

Two-phase design (pipelines.md §2): non-regime-guarded rules can match with regime=None; guarded
rules are resolved once the regime is known. This facade accepts an optional regime so the caller
can run either phase; passing the final regime yields the complete activation set.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_state_engine.core.dtos import EventFeature
from market_state_engine.core.enums import RegimeState

from . import matcher as matcher_mod
from .conflict import (
    ConflictFlag,
    ResolvedEffect,
    resolve_asset_effects,
)
from .models import Effect, Rule


@dataclass(frozen=True)
class Activation:
    asset: str
    rule_id: str
    strength: str
    horizon: str
    decay_remaining: float
    direction: str
    event_id: str | None
    matched_condition: str
    source_rule_version: int


def build_condition_vars(events: list[EventFeature]) -> dict[str, float]:
    """Map event surprises to condition variables.

    Convention: each event type exposes ``surprise_<event_type>`` and, for CPI, the canonical
    ``surprise_core_mom`` alias used by the seed rulebook.
    """
    variables: dict[str, float] = {}
    for e in events:
        variables[f"surprise_{e.event_type}"] = e.surprise
        if e.event_type == "us_cpi":
            variables["surprise_core_mom"] = e.surprise
    return variables


class RuleEngine:
    def __init__(self, rules: list[Rule], half_life_default_hours: float = 12.0) -> None:
        self._rules = rules
        self._half_life_default = half_life_default_hours

    def match(
        self,
        events: list[EventFeature],
        regime: RegimeState | None,
    ) -> tuple[dict[str, list[Activation]], list[ConflictFlag]]:
        variables = build_condition_vars(events)
        event_by_type = {e.event_type: e for e in events}

        # Collect candidate effects per asset: (Effect, rule_id, rule, event).
        per_asset_candidates: dict[str, list[tuple[Effect, str]]] = {}
        meta: dict[tuple[str, str], tuple[Rule, EventFeature | None]] = {}
        for rule in self._rules:
            if not matcher_mod.rule_matches(rule, variables):
                continue
            effects = matcher_mod.resolved_effects(rule, regime)
            event = (
                event_by_type.get(rule.trigger.event_type.value)
                if rule.trigger.event_type is not None
                else None
            )
            for eff in effects:
                per_asset_candidates.setdefault(eff.asset, []).append((eff, rule.id))
                meta[(eff.asset, rule.id)] = (rule, event)

        activations: dict[str, list[Activation]] = {}
        flags: list[ConflictFlag] = []
        for asset, candidates in per_asset_candidates.items():
            resolved, flag = resolve_asset_effects(asset, candidates)
            if flag is not None:
                flags.append(flag)
            if resolved is None:
                continue
            rule, event = meta[(asset, resolved.source_rule_id)]
            activations.setdefault(asset, []).append(
                self._to_activation(asset, resolved, rule, event)
            )
        return activations, flags

    def _to_activation(
        self,
        asset: str,
        resolved: ResolvedEffect,
        rule: Rule,
        event: EventFeature | None,
    ) -> Activation:
        half_life = rule.half_life_hours or self._half_life_default
        proximity = abs(event.proximity_hours) if event is not None else 0.0
        decay = 0.5 ** (proximity / half_life)
        decay = max(0.0, min(1.0, decay))
        return Activation(
            asset=asset,
            rule_id=rule.id,
            strength=resolved.strength.value,
            horizon=resolved.horizon,
            decay_remaining=round(decay, 4),
            direction=resolved.direction.value,
            event_id=event.event_id if event is not None else None,
            matched_condition=rule.trigger.condition,
            source_rule_version=rule.version,
        )
