"""Rule matching: deterministic, surprise-based condition evaluation + regime guards.

Conditions are simple comparisons of the form ``<var> <op> <number>`` (e.g.
``surprise_core_mom >= 0.1``). We parse them without ``eval`` for safety and determinism. The
variable values come from a context dict the RuleEngine builds from event features.
"""

from __future__ import annotations

import re

from market_state_engine.core.enums import OrdinalLevel, RegimeState
from market_state_engine.core.errors import RuleGateError

from .models import Effect, Rule

_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}

# Match: <identifier> <op> <number>. Operators tried longest-first via alternation ordering.
_CONDITION_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$"
)


def evaluate_condition(condition: str, variables: dict[str, float]) -> bool:
    m = _CONDITION_RE.match(condition)
    if m is None:
        raise RuleGateError(f"unsupported rule condition syntax: {condition!r}")
    var_name, op, literal = m.group(1), m.group(2), m.group(3)
    if var_name not in variables:
        # A referenced variable with no value cannot match (deterministic, never raises mid-run).
        return False
    result: bool = _COMPARATORS[op](variables[var_name], float(literal))
    return result


def _downgrade(effect: Effect) -> Effect:
    return effect.model_copy(update={"strength": OrdinalLevel.MINOR, "uncertain": True})


def resolved_effects(rule: Rule, regime: RegimeState | None) -> list[Effect]:
    """Apply the regime guard to a matched rule's effects.

    If the rule has no guard, effects pass through. If guarded and the current regime is in
    ``applies_in``, effects pass through; otherwise the ``else`` policy is applied:
      - suppress            -> drop the effects
      - downgrade_to_minor  -> minor + uncertain
      - flag_uncertain      -> keep strength but mark uncertain
    """
    guard = rule.regime_guard
    if guard is None:
        return list(rule.effects)
    in_regime = regime is not None and regime in guard.applies_in
    if in_regime:
        return list(rule.effects)
    policy = guard.else_
    if policy == "suppress":
        return []
    if policy == "downgrade_to_minor":
        return [_downgrade(e) for e in rule.effects]
    if policy == "flag_uncertain":
        return [e.model_copy(update={"uncertain": True}) for e in rule.effects]
    raise RuleGateError(f"rule {rule.id}: unknown regime_guard.else policy {policy!r}")


def rule_matches(rule: Rule, variables: dict[str, float]) -> bool:
    if rule.status != "active":
        return False
    return evaluate_condition(rule.trigger.condition, variables)
