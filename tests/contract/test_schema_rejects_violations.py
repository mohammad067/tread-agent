"""Negative contract tests: the frozen schema must REJECT violations.

Proves the constraints are actually enforced (additionalProperties:false forbids invented
fields; closed enums reject unknown values; the Driver oneOf enforces honest weights).
Each test starts from the valid normal fixture and mutates one thing.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest


def _is_invalid(validator: Any, doc: Any) -> bool:
    return bool(list(validator.iter_errors(doc)))


@pytest.mark.contract
def test_rejects_invented_top_level_field(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["extra_invented_field"] = "nope"
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_invented_asset_field(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["assets"][0]["proxy_note"] = "USDT proxy"
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_unknown_regime_state(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["regime"]["state"] = "super_bull"
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_computed_driver_with_level(load_golden_json: Any, make_validator: Any) -> None:
    """Honest-weights oneOf: a computed driver may not also carry an ordinal level."""
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["regime"]["drivers"][0]["level"] = "major"  # computed driver + level => invalid
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_ordinal_driver_with_weight(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    ordinal = next(d for d in doc["regime"]["drivers"] if d["weight_type"] == "ordinal")
    ordinal["weight"] = 0.5  # ordinal driver + weight => invalid
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_missing_required_field(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    del doc["disclaimer"]
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_out_of_range_score(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["assets"][0]["scores"]["trend"] = 2.5  # outside [-1, 1]
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rejects_wrong_schema_version(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = copy.deepcopy(load_golden_json("market_state_run.normal.json"))
    doc["schema_version"] = "2.0.0"  # const 1.0.0
    assert _is_invalid(validator, doc)


@pytest.mark.contract
def test_rule_schema_rejects_missing_signoff(load_golden_yaml: Any, make_validator: Any) -> None:
    """ADR-008 hard gate at the schema level: reviewed_by must equal senior_trader."""
    validator = make_validator("rule.v1.json")
    rule = copy.deepcopy(load_golden_yaml("rule.cpi_hot.corrected.yaml"))
    rule["reviewed_by"] = "some_engineer"
    assert _is_invalid(validator, rule)


@pytest.mark.contract
def test_rule_schema_rejects_empty_rationale(load_golden_yaml: Any, make_validator: Any) -> None:
    validator = make_validator("rule.v1.json")
    rule = copy.deepcopy(load_golden_yaml("rule.cpi_hot.corrected.yaml"))
    rule["economic_rationale"] = ""  # minLength 1
    assert _is_invalid(validator, rule)
