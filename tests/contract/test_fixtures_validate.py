"""Every golden fixture validates against its corresponding frozen schema (§C.3.1)."""

from __future__ import annotations

from typing import Any

import pytest

# (fixture filename, schema filename) pairs.
MARKET_STATE_FIXTURES = [
    "market_state_run.normal.json",
    "market_state_run.degraded.json",
    "market_state_run.stale_usdirr.json",
]

REASONING_REQUEST_FIXTURES = [
    "reasoning_request.sentiment.json",
    "reasoning_request.synthesis.json",
]


@pytest.mark.contract
@pytest.mark.parametrize("fixture_name", MARKET_STATE_FIXTURES)
def test_market_state_fixture_validates(
    fixture_name: str, load_golden_json: Any, make_validator: Any
) -> None:
    validator = make_validator("market_state_run.v1.0.0.json")
    doc = load_golden_json(fixture_name)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.mark.contract
@pytest.mark.parametrize("fixture_name", REASONING_REQUEST_FIXTURES)
def test_reasoning_request_fixture_validates(
    fixture_name: str, load_golden_json: Any, make_validator: Any
) -> None:
    validator = make_validator("reasoning_request.v1.json")
    doc = load_golden_json(fixture_name)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.mark.contract
def test_call_record_fixture_validates(load_golden_json: Any, make_validator: Any) -> None:
    validator = make_validator("call_record.v1.json")
    doc = load_golden_json("call_record.example.json")
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.mark.contract
def test_corrected_rule_fixture_validates(load_golden_yaml: Any, make_validator: Any) -> None:
    validator = make_validator("rule.v1.json")
    doc = load_golden_yaml("rule.cpi_hot.corrected.yaml")
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)
