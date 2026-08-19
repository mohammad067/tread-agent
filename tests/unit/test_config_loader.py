"""Config loader tests: real config files load and validate; malformed config fails fast."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from market_state_engine.config.loader import (
    ASSET_SYMBOLS,
    load_config_bundle,
    load_env_config,
)
from market_state_engine.config.models import MhiWeights
from market_state_engine.core.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_load_all_asset_configs() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    assert set(bundle.assets) == {"BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"}
    assert len(ASSET_SYMBOLS) == 6


def test_usd_irr_is_low_sensitivity_irt() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    usd_irr = bundle.assets["USD_IRR"]
    assert usd_irr.regime_sensitivity.value == "low"
    assert usd_irr.source is not None
    assert usd_irr.source.currency == "IRT"


def test_total_mcap_reduced_indicator_set() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    total = bundle.assets["TOTAL_MCAP"]
    assert "rsi_14" not in total.indicators
    assert "atr_pct" in total.indicators


def test_mhi_weights_sum_to_one() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    assert abs(sum(bundle.mhi_weights.weights.values()) - 1.0) < 1e-6


def test_bundle_versions_captured() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    assert bundle.versions["mhi_weights"] == "1.1.0"
    assert bundle.versions["source_quality"]
    assert bundle.versions["half_lives"] == "1.1.0"
    assert bundle.half_lives.max_news_age_hours == 36.0


def test_env_configs_load() -> None:
    for env in ("dev", "staging", "prod"):
        cfg = load_env_config(CONFIG_DIR, env)
        assert cfg.env == env


def test_missing_config_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config_bundle(tmp_path)


def test_mhi_weights_not_summing_to_one_rejected() -> None:
    with pytest.raises(ValidationError):
        MhiWeights(version="1.0.0", weights={"trend": 0.5, "risk": 0.2})
