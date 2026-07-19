"""Every materialized schema must itself be a valid JSON Schema (Draft 2020-12).

This guards against typos in the frozen contract files before any fixture is validated
against them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import INTERNAL_SCHEMAS_DIR, SCHEMAS_DIR

ALL_SCHEMA_FILES = [
    SCHEMAS_DIR / "market_state_run.v1.0.0.json",
    *sorted(INTERNAL_SCHEMAS_DIR.glob("*.json")),
]

EXPECTED_INTERNAL_SCHEMAS = {
    "raw_snapshot.v1.json",
    "feature_set.v1.json",
    "news_digest.v1.json",
    "reasoning_request.v1.json",
    "reasoning_response.v1.json",
    "state_vector.v1.json",
    "rule_activation.v1.json",
    "causal_link.v1.json",
    "call_record.v1.json",
    "degraded_marker.v1.json",
    "rule.v1.json",
}


@pytest.mark.contract
@pytest.mark.parametrize("schema_path", ALL_SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_draft202012(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Raises SchemaError if the schema itself is malformed.
    Draft202012Validator.check_schema(schema)


@pytest.mark.contract
def test_all_expected_internal_schemas_present() -> None:
    present = {p.name for p in INTERNAL_SCHEMAS_DIR.glob("*.json")}
    assert present == EXPECTED_INTERNAL_SCHEMAS
