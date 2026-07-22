"""Reasoning DTOs round-trip the golden fixtures and re-serialize to valid documents (M4.1)."""

from __future__ import annotations

from typing import Any

import pytest

from market_state_engine.reasoning.models import (
    CallRecord,
    DegradedMarker,
    ReasoningRequest,
)


@pytest.mark.contract
@pytest.mark.parametrize(
    "fixture_name",
    ["reasoning_request.sentiment.json", "reasoning_request.synthesis.json"],
)
def test_reasoning_request_roundtrips(
    fixture_name: str, load_golden_json: Any, make_validator: Any
) -> None:
    original = load_golden_json(fixture_name)
    out = ReasoningRequest.model_validate(original).to_contract_dict()
    validator = make_validator("reasoning_request.v1.json")
    errors = sorted(validator.iter_errors(out), key=str)
    assert not errors, "\n".join(e.message for e in errors)


@pytest.mark.contract
def test_call_record_roundtrips(load_golden_json: Any, make_validator: Any) -> None:
    original = load_golden_json("call_record.example.json")
    out = CallRecord.model_validate(original).to_contract_dict()
    validator = make_validator("call_record.v1.json")
    errors = sorted(validator.iter_errors(out), key=str)
    assert not errors, "\n".join(e.message for e in errors)


@pytest.mark.contract
def test_degraded_marker_serializes_valid(make_validator: Any) -> None:
    marker = DegradedMarker.model_validate(
        {
            "job": "synthesis",
            "reason": "all providers exhausted",
            "last_attempt": {"provider": "openai", "model_id": "gpt-5.5"},
        }
    )
    validator = make_validator("degraded_marker.v1.json")
    errors = list(validator.iter_errors(marker.to_contract_dict()))
    assert not errors
