"""Rule loader with the ADR-008 hard sign-off gate and load-time lints.

Rejects (fail-fast, RuleGateError):
  1. any rule missing economic_rationale or reviewed_by != senior_trader (ADR-008);
  2. an event-typed rule whose condition does not reference a surprise_* variable (F-5);
  3. an unguarded non-`minor` GOLD effect on a hot-CPI trigger (challenge A4).
Also validates each rule against the frozen rule schema shape via the Pydantic model.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from market_state_engine.core.enums import EventType, OrdinalLevel
from market_state_engine.core.errors import RuleGateError

from .models import Rule

_REQUIRED_REVIEWER = "senior_trader"


def _lint_signoff(rule: Rule) -> None:
    if not rule.economic_rationale.strip():
        raise RuleGateError(f"rule {rule.id}: empty economic_rationale (ADR-008)")
    if rule.reviewed_by != _REQUIRED_REVIEWER:
        raise RuleGateError(
            f"rule {rule.id}: reviewed_by must be '{_REQUIRED_REVIEWER}' (ADR-008), "
            f"got '{rule.reviewed_by}'"
        )


def _lint_surprise(rule: Rule) -> None:
    if rule.trigger.event_type is None:
        return
    refs_surprise = any(v.startswith("surprise") for v in rule.trigger.condition_vars)
    if not refs_surprise:
        raise RuleGateError(
            f"rule {rule.id}: event-typed condition must reference a surprise_* variable (F-5)"
        )


def _lint_gold_cpi(rule: Rule) -> None:
    if rule.trigger.event_type is not EventType.US_CPI:
        return
    guarded = rule.regime_guard is not None
    for eff in rule.effects:
        if eff.asset != "GOLD":
            continue
        if guarded:
            continue
        if not (eff.strength is OrdinalLevel.MINOR and eff.uncertain is True):
            raise RuleGateError(
                f"rule {rule.id}: unguarded GOLD effect on a hot-CPI trigger must be "
                f"regime-guarded or minor+uncertain (A4)"
            )


def validate_rule(rule: Rule) -> None:
    _lint_signoff(rule)
    _lint_surprise(rule)
    _lint_gold_cpi(rule)


def load_rule_dict(data: dict[str, object], where: str = "<memory>") -> Rule:
    try:
        rule = Rule.model_validate(data)
    except ValidationError as exc:
        raise RuleGateError(f"rule schema validation failed for {where}: {exc}") from exc
    validate_rule(rule)
    return rule


def load_rulebook(rules_dir: Path) -> list[Rule]:
    """Load every *.yaml rule under rules_dir (recursively), enforcing the gate on each."""
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for path in sorted(rules_dir.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuleGateError(f"rule file {path} must contain a mapping")
        rule = load_rule_dict(raw, str(path))
        if rule.id in seen_ids:
            raise RuleGateError(f"duplicate rule id: {rule.id}")
        seen_ids.add(rule.id)
        rules.append(rule)
    return rules


def read_rulebook_version(rules_dir: Path) -> str:
    version_file = rules_dir / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"
