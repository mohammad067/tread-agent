"""Typed configuration models (config-contracts.md). Validated on load; fail-fast."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_state_engine.core.enums import AssetClass, RegimeSensitivity


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoiseThreshold(_Cfg):
    k: float = Field(ge=0.0)
    floor_pct: dict[str, float]


class PriceSourcesCfg(_Cfg):
    aggregation: str
    min_sources: int = Field(ge=1)
    max_deviation_pct: float = Field(ge=0.0)


class AssetSourceCfg(_Cfg):
    provider: str
    field: str
    currency: str


class AssetConfig(_Cfg):
    symbol: str
    display_name: str
    asset_class: AssetClass
    regime_sensitivity: RegimeSensitivity
    decimals: int = Field(ge=0)
    trading_hours: str
    staleness_threshold_minutes: int = Field(ge=0)
    noise_threshold: NoiseThreshold
    indicators: list[str]
    rules_dir: str
    price_sources: PriceSourcesCfg | None = None
    source: AssetSourceCfg | None = None


class MhiWeights(_Cfg):
    version: str
    weights: dict[str, float]
    per_asset_overrides: dict[str, dict[str, float]] | None = None

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> MhiWeights:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"mhi weights must sum to 1.0, got {total}")
        return self


class SourceQuality(_Cfg):
    version: str
    sources: dict[str, float]
    default_quality: float = Field(ge=0.0, le=1.0)


class HalfLives(_Cfg):
    version: str
    news_half_life_hours: dict[str, float]
    rule_half_life_defaults: dict[str, float]
    max_news_age_hours: float = Field(gt=0.0)


class DatabaseCfg(_Cfg):
    dialect: str
    dsn_env: str | None = None


class BudgetCfg(_Cfg):
    monthly_llm_budget: float
    currency: str
    alert_pct: int = Field(ge=0, le=100)


class SchedulerCfg(_Cfg):
    scheduled_cron: str
    event_cooldown_minutes: int = Field(ge=0)


class EnvConfig(_Cfg):
    env: str
    database: DatabaseCfg
    ingestion: dict[str, str]
    llm: dict[str, str]
    scheduler: SchedulerCfg
    budget: BudgetCfg
