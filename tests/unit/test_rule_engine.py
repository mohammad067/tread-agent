"""Rule engine tests: ADR-008 gate, surprise/gold lints, matcher, guards, conflict (OQ-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_state_engine.core.dtos import EventFeature
from market_state_engine.core.enums import Direction, OrdinalLevel, RegimeState
from market_state_engine.core.errors import RuleGateError
from market_state_engine.rules.conflict import resolve_asset_effects
from market_state_engine.rules.engine import RuleEngine
from market_state_engine.rules.loader import load_rule_dict, load_rulebook, read_rulebook_version
from market_state_engine.rules.matcher import evaluate_condition, resolved_effects
from market_state_engine.rules.models import Effect

REPO = Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "rules"


def _base_rule(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "test_rule",
        "version": 1,
        "status": "active",
        "trigger": {
            "event_type": "us_cpi",
            "condition": "surprise_core_mom >= 0.1",
            "condition_vars": ["surprise_core_mom"],
        },
        "effects": [
            {"asset": "BTC", "direction": "bearish", "strength": "major", "horizon": "24h"}
        ],
        "half_life_hours": 12,
        "source": "test",
        "economic_rationale": "test rationale",
        "reviewed_by": "senior_trader",
        "reviewed_at": "2026-06-02",
    }
    data.update(overrides)
    return data


# --- ADR-008 hard gate ---
def test_gate_rejects_missing_signoff() -> None:
    with pytest.raises(RuleGateError):
        load_rule_dict(_base_rule(reviewed_by="engineer"))


def test_gate_rejects_empty_rationale() -> None:
    with pytest.raises(RuleGateError):
        load_rule_dict(_base_rule(economic_rationale="   "))


def test_gate_rejects_event_without_surprise_var() -> None:
    bad = _base_rule(
        trigger={"event_type": "us_cpi", "condition": "actual >= 0.4", "condition_vars": ["actual"]}
    )
    with pytest.raises(RuleGateError):
        load_rule_dict(bad)


def test_gate_rejects_unguarded_gold_cpi() -> None:
    bad = _base_rule(
        effects=[
            {"asset": "GOLD", "direction": "bearish", "strength": "moderate", "horizon": "24h"}
        ]
    )
    with pytest.raises(RuleGateError):
        load_rule_dict(bad)


def test_gate_accepts_gold_minor_uncertain() -> None:
    ok = _base_rule(
        effects=[
            {
                "asset": "GOLD",
                "direction": "bearish",
                "strength": "minor",
                "horizon": "24h",
                "uncertain": True,
            }
        ]
    )
    rule = load_rule_dict(ok)
    assert rule.id == "test_rule"


def test_gate_accepts_gold_with_regime_guard() -> None:
    ok = _base_rule(
        effects=[
            {"asset": "GOLD", "direction": "bearish", "strength": "moderate", "horizon": "24h"}
        ],
        regime_guard={"applies_in": ["risk_off"], "else": "downgrade_to_minor"},
    )
    rule = load_rule_dict(ok)
    assert rule.regime_guard is not None


# --- Seed rulebook loads through the gate ---
def test_seed_rulebook_loads() -> None:
    rules = load_rulebook(RULES_DIR)
    assert len(rules) >= 2
    assert read_rulebook_version(RULES_DIR) == "1.4.0"


# --- Condition evaluation ---
def test_condition_operators() -> None:
    assert evaluate_condition("surprise_core_mom >= 0.1", {"surprise_core_mom": 0.1}) is True
    assert evaluate_condition("surprise_core_mom >= 0.1", {"surprise_core_mom": 0.05}) is False
    assert evaluate_condition("x <= -0.1", {"x": -0.2}) is True


def test_condition_missing_var_no_match() -> None:
    assert evaluate_condition("y >= 1", {}) is False


def test_condition_bad_syntax_raises() -> None:
    with pytest.raises(RuleGateError):
        evaluate_condition("surprise and something", {})


def test_condition_all_operators() -> None:
    assert evaluate_condition("x == 1", {"x": 1.0}) is True
    assert evaluate_condition("x != 1", {"x": 2.0}) is True
    assert evaluate_condition("x > 0", {"x": 0.5}) is True
    assert evaluate_condition("x < 0", {"x": -0.5}) is True


def test_inactive_rule_does_not_match() -> None:
    from market_state_engine.rules.matcher import rule_matches

    rule = load_rule_dict(_base_rule(status="inactive"))
    assert rule_matches(rule, {"surprise_core_mom": 0.5}) is False


def test_duplicate_rule_id_rejected(tmp_path: Path) -> None:
    import yaml

    from market_state_engine.rules.loader import load_rulebook as _lr

    d = tmp_path / "rules"
    (d / "a").mkdir(parents=True)
    (d / "b").mkdir(parents=True)
    rule = _base_rule()
    (d / "a" / "r.yaml").write_text(yaml.safe_dump(rule), encoding="utf-8")
    (d / "b" / "r.yaml").write_text(yaml.safe_dump(rule), encoding="utf-8")
    with pytest.raises(RuleGateError):
        _lr(d)


# --- Regime guards ---
def test_regime_guard_downgrades_outside_regime() -> None:
    rule = load_rule_dict(
        _base_rule(
            effects=[
                {"asset": "BTC", "direction": "bearish", "strength": "major", "horizon": "24h"}
            ],
            regime_guard={"applies_in": ["risk_off"], "else": "downgrade_to_minor"},
        )
    )
    effects = resolved_effects(rule, RegimeState.RISK_ON)
    assert effects[0].strength is OrdinalLevel.MINOR
    assert effects[0].uncertain is True


def test_regime_guard_flag_uncertain_keeps_strength() -> None:
    rule = load_rule_dict(
        _base_rule(
            effects=[
                {"asset": "BTC", "direction": "bearish", "strength": "major", "horizon": "24h"}
            ],
            regime_guard={"applies_in": ["risk_off"], "else": "flag_uncertain"},
        )
    )
    effects = resolved_effects(rule, RegimeState.RISK_ON)
    assert effects[0].strength is OrdinalLevel.MAJOR
    assert effects[0].uncertain is True


def test_regime_guard_no_guard_passthrough() -> None:
    rule = load_rule_dict(_base_rule())
    effects = resolved_effects(rule, None)
    assert effects[0].strength is OrdinalLevel.MAJOR


def test_regime_guard_passes_inside_regime() -> None:
    rule = load_rule_dict(
        _base_rule(
            effects=[
                {"asset": "BTC", "direction": "bearish", "strength": "major", "horizon": "24h"}
            ],
            regime_guard={"applies_in": ["risk_off"], "else": "suppress"},
        )
    )
    assert resolved_effects(rule, RegimeState.RISK_OFF)[0].strength is OrdinalLevel.MAJOR
    assert resolved_effects(rule, RegimeState.RISK_ON) == []


# --- Conflict resolution (OQ-3) ---
def _eff(direction: str, strength: str) -> Effect:
    return Effect.model_validate(
        {"asset": "BTC", "direction": direction, "strength": strength, "horizon": "24h"}
    )


def test_conflict_highest_strength_wins() -> None:
    resolved, flag = resolve_asset_effects(
        "BTC", [(_eff("bearish", "major"), "r1"), (_eff("bullish", "minor"), "r2")]
    )
    assert resolved is not None
    assert resolved.direction is Direction.BEARISH
    assert flag is None


def test_conflict_equal_strength_to_neutral_with_flag() -> None:
    resolved, flag = resolve_asset_effects(
        "BTC", [(_eff("bearish", "major"), "r1"), (_eff("bullish", "major"), "r2")]
    )
    assert resolved is not None
    assert resolved.direction is Direction.NEUTRAL
    assert flag is not None
    assert "neutral" in flag.detail.lower()


def test_conflict_same_direction_keeps_strongest() -> None:
    resolved, flag = resolve_asset_effects(
        "BTC", [(_eff("bearish", "moderate"), "r1"), (_eff("bearish", "major"), "r2")]
    )
    assert resolved is not None
    assert resolved.strength is OrdinalLevel.MAJOR
    assert flag is None


# --- End-to-end matching ---
def test_rule_engine_activates_on_hot_cpi() -> None:
    rules = load_rulebook(RULES_DIR)
    engine = RuleEngine(rules)
    events = [
        EventFeature(
            event_id="us_cpi_2026_07",
            event_type="us_cpi",
            surprise=0.15,
            surprise_sigma=1.3,
            proximity_hours=2.0,
        )
    ]
    activations, _flags = engine.match(events, RegimeState.RISK_OFF)
    assert "BTC" in activations
    btc = activations["BTC"][0]
    assert btc.rule_id == "cpi_hot_risk_assets_bearish"
    assert 0.0 <= btc.decay_remaining <= 1.0
    assert btc.direction == "bearish"


def test_rule_engine_no_activation_below_threshold() -> None:
    rules = load_rulebook(RULES_DIR)
    engine = RuleEngine(rules)
    events = [
        EventFeature(
            event_id="us_cpi_2026_07",
            event_type="us_cpi",
            surprise=0.02,
            surprise_sigma=0.2,
            proximity_hours=2.0,
        )
    ]
    activations, _ = engine.match(events, RegimeState.TRANSITION)
    assert activations == {}


def test_rule_engine_deterministic() -> None:
    rules = load_rulebook(RULES_DIR)
    engine = RuleEngine(rules)
    events = [
        EventFeature(
            event_id="us_cpi_2026_07",
            event_type="us_cpi",
            surprise=0.15,
            surprise_sigma=1.3,
            proximity_hours=2.0,
        )
    ]
    a1, _ = engine.match(events, RegimeState.RISK_OFF)
    a2, _ = engine.match(events, RegimeState.RISK_OFF)
    assert a1 == a2
