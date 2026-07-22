"""Versioned pricing tests (M4.4): automatic estimated_cost from token counts (ADR-007 D-6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_state_engine.reasoning.errors import ProviderConfigError
from market_state_engine.reasoning.pricing import PriceTable

REPO = Path(__file__).resolve().parents[2]
PRICING_YAML = REPO / "config" / "models" / "pricing.v1.yaml"


def test_loads_frozen_pricing_file() -> None:
    table = PriceTable.from_file(PRICING_YAML)
    assert table.version == "1.0.0"


def test_estimate_is_token_weighted() -> None:
    table = PriceTable.from_file(PRICING_YAML)
    # gpt-5.5: input 0.005/1k, output 0.015/1k. 1000 in + 1000 out = 0.005 + 0.015 = 0.02
    assert table.estimate("gpt-5.5", 1000, 1000) == pytest.approx(0.02)


def test_estimate_none_when_tokens_absent() -> None:
    table = PriceTable.from_file(PRICING_YAML)
    assert table.estimate("gpt-5.5", None, None) is None


def test_estimate_partial_tokens_treats_missing_as_zero() -> None:
    table = PriceTable.from_file(PRICING_YAML)
    assert table.estimate("gpt-5.5", 1000, None) == pytest.approx(0.005)


def test_unknown_model_uses_default_rate() -> None:
    table = PriceTable.from_file(PRICING_YAML)
    # default rate is 0 in the frozen file → cost 0, not an error.
    assert table.estimate("some-future-model", 5000, 5000) == 0.0


def test_missing_file_fails_fast() -> None:
    with pytest.raises(ProviderConfigError):
        PriceTable.from_file(REPO / "config" / "models" / "does_not_exist.yaml")


def test_non_mapping_file_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="mapping"):
        PriceTable.from_file(path)


def test_invalid_schema_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text("version: '1.0.0'\n", encoding="utf-8")  # missing required 'default'/'models'
    with pytest.raises(ProviderConfigError, match="invalid"):
        PriceTable.from_file(path)
