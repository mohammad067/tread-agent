"""The Pydantic domain models round-trip the golden fixtures without loss, and re-serialize to
schema-valid contract documents (aliases, nullable-vs-optional handling)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from market_state_engine.core.models import MarketStateRun

FIXTURES = [
    "market_state_run.normal.json",
    "market_state_run.degraded.json",
    "market_state_run.stale_usdirr.json",
]


@pytest.mark.contract
@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_model_parses_and_reserializes_valid(
    fixture_name: str, load_golden_json: Any, make_validator: Any
) -> None:
    original = load_golden_json(fixture_name)
    model = MarketStateRun.model_validate(original)
    out = model.to_contract_dict()

    validator = make_validator("market_state_run.v1.0.0.json")
    errors = sorted(validator.iter_errors(out), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


@pytest.mark.contract
def test_roundtrip_preserves_key_fields(load_golden_json: Any) -> None:
    original = load_golden_json("market_state_run.normal.json")
    out = MarketStateRun.model_validate(original).to_contract_dict()
    assert out["schema_version"] == "1.0.0"
    assert out["is_degraded"] is False
    # `global` and `from` aliases preserved.
    assert "global" in out
    btc = next(a for a in out["assets"] if a["symbol"] == "BTC")
    assert btc["causal_links"][0]["from"] == "us_cpi_2026_07"
    assert btc["changes"]["6h"] == -2.8


@pytest.mark.contract
def test_degraded_roundtrip_keeps_null_sentiment_and_omits_summary(load_golden_json: Any) -> None:
    original = load_golden_json("market_state_run.degraded.json")
    out = MarketStateRun.model_validate(original).to_contract_dict()
    assert out["is_degraded"] is True
    for asset in out["assets"]:
        assert asset["scores"]["sentiment"] is None
        assert "human_summary_fa" not in asset


@pytest.mark.contract
def test_computed_driver_with_level_is_rejected_by_model(load_golden_json: Any) -> None:
    doc = load_golden_json("market_state_run.normal.json")
    doc["regime"]["drivers"][0]["level"] = "major"  # computed + level
    with pytest.raises(ValidationError):
        MarketStateRun.model_validate(doc)
