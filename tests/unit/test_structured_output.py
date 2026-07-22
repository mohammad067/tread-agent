"""Structured-output validation tests (M4.1): valid responses parse; bad ones are call failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_state_engine.core.enums import LlmJob
from market_state_engine.reasoning.errors import StructuredOutputError
from market_state_engine.reasoning.structured_output import StructuredOutputValidator

REPO = Path(__file__).resolve().parents[2]
INTERNAL_SCHEMAS = REPO / "schemas" / "internal"


def _validator() -> StructuredOutputValidator:
    return StructuredOutputValidator(INTERNAL_SCHEMAS)


def test_valid_sentiment_response_builds() -> None:
    data = {"per_asset_sentiment": {"BTC": -0.38, "ETH": -0.41}, "global_sentiment": -0.35}
    resp = _validator().build_sentiment(data)
    assert resp.global_sentiment == pytest.approx(-0.35)
    assert resp.per_asset_sentiment["BTC"] == pytest.approx(-0.38)


def test_valid_synthesis_response_builds() -> None:
    data = {
        "per_asset": {
            "BTC": {
                "human_summary_fa": "خلاصه",
                "ordinal_drivers": [{"name": "cpi", "weight_type": "ordinal", "level": "major"}],
                "novelty_flags": [],
                "data_gap_notes": [],
            }
        },
        "grounding_ok": True,
    }
    resp = _validator().build_synthesis(data)
    assert "BTC" in resp.per_asset


def test_non_json_is_call_failure() -> None:
    with pytest.raises(StructuredOutputError):
        _validator().parse_json("not-json{")


def test_non_object_json_is_call_failure() -> None:
    with pytest.raises(StructuredOutputError):
        _validator().parse_json("[1, 2, 3]")


def test_out_of_range_sentiment_rejected() -> None:
    data = {"per_asset_sentiment": {"BTC": 2.0}, "global_sentiment": 0.0}
    with pytest.raises(StructuredOutputError):
        _validator().validate(LlmJob.SENTIMENT, data)


def test_extra_property_rejected() -> None:
    data = {"per_asset_sentiment": {}, "global_sentiment": 0.0, "extra": 1}
    with pytest.raises(StructuredOutputError):
        _validator().validate(LlmJob.SENTIMENT, data)


def test_synthesis_missing_required_rejected() -> None:
    data = {"per_asset": {"BTC": {"human_summary_fa": "x"}}}  # missing ordinal_drivers, etc.
    with pytest.raises(StructuredOutputError):
        _validator().validate(LlmJob.SYNTHESIS, data)


def test_sentiment_blob_not_accepted_as_synthesis() -> None:
    # Guards the per-job $ref selection: a sentiment payload must fail synthesis validation.
    data = {"per_asset_sentiment": {"BTC": 0.1}, "global_sentiment": 0.1}
    with pytest.raises(StructuredOutputError):
        _validator().validate(LlmJob.SYNTHESIS, data)


def test_missing_schema_file_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(StructuredOutputError):
        StructuredOutputValidator(tmp_path)  # no reasoning_response.v1.json here


def test_sentiment_response_to_contract_dict_roundtrips() -> None:
    data = {"per_asset_sentiment": {"BTC": -0.1}, "global_sentiment": -0.1}
    out = _validator().build_sentiment(data).to_contract_dict()
    assert out["global_sentiment"] == pytest.approx(-0.1)
    assert "confidence_signals" not in out  # optional None pruned


def test_synthesis_response_to_contract_dict_roundtrips() -> None:
    data = {
        "per_asset": {
            "BTC": {
                "human_summary_fa": "خ",
                "ordinal_drivers": [],
                "novelty_flags": [],
                "data_gap_notes": [],
            }
        }
    }
    out = _validator().build_synthesis(data).to_contract_dict()
    assert "BTC" in out["per_asset"]  # type: ignore[operator]
