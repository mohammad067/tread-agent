"""Public-contract domain models (MarketStateRun and its parts).

Pydantic v2 models mirroring schemas/market_state_run.v1.0.0.json exactly: field names, types,
enums, ranges, and ``extra="forbid"`` == ``additionalProperties: false``. Serialization uses the
exact contract field names (including ``from`` and the change-horizon keys ``6h``/``24h``/... via
aliases). No field may be renamed, added, or removed here without a contract change.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    AssetClass,
    Currency,
    Direction,
    EmaState,
    FearGreedLabel,
    MacdState,
    OrdinalLevel,
    RegimeSensitivity,
    RegimeState,
    Severity,
    TriggerType,
    WeightType,
)
from .serialization import prune_none

SCHEMA_VERSION = "1.0.0"


class _Contract(BaseModel):
    """Base: forbid unknown fields (mirrors additionalProperties:false), populate by alias."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TriggerDetail(_Contract):
    event_id: str | None = None
    debounced_events: int | None = Field(default=None, ge=0)
    scheduled_for: str | None = None


class Versions(_Contract):
    rulebook: str
    mhi_weights: str
    prompt_sentiment: str
    prompt_synthesis: str
    provider: str
    model: str
    pipeline: str
    pricing: str


class Driver(_Contract):
    name: str
    weight_type: WeightType
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    level: OrdinalLevel | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def _exactly_one_of_weight_or_level(self) -> Driver:
        if self.weight_type is WeightType.COMPUTED:
            if self.weight is None or self.level is not None:
                raise ValueError("computed driver must have `weight` and no `level`")
        else:  # ORDINAL
            if self.level is None or self.weight is not None:
                raise ValueError("ordinal driver must have `level` and no `weight`")
        return self


class Regime(_Contract):
    state: RegimeState
    previous_state: RegimeState | None
    changed_this_run: bool
    confidence: float = Field(ge=0.0, le=1.0)
    drivers: list[Driver]


class Price(_Contract):
    value: float
    currency: Currency
    as_of: str
    is_stale: bool
    stale_reason: str | None = None
    venue_aggregation: str | None = None


class Changes(_Contract):
    h6: float = Field(alias="6h")
    h24: float = Field(alias="24h")
    d7: float = Field(alias="7d")
    d30: float = Field(alias="30d")


class Indicators(_Contract):
    rsi_14: float | None = Field(default=None, ge=0.0, le=100.0)
    macd_state: MacdState | None = None
    ema_20_50: EmaState | None = None
    atr_pct: float | None = Field(default=None, ge=0.0)
    volume_ratio_20d: float | None = Field(default=None, ge=0.0)
    trend_state: str | None = None
    dominance_shift: float | None = None


class Scores(_Contract):
    trend: float = Field(ge=-1.0, le=1.0)
    risk: float = Field(ge=0.0, le=1.0)
    sentiment: float | None = Field(default=..., ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class RuleActivation(_Contract):
    rule_id: str
    strength: OrdinalLevel
    horizon: str
    decay_remaining: float = Field(ge=0.0, le=1.0)


class CausalLink(_Contract):
    from_: str = Field(alias="from")
    to: str
    direction: Direction
    via_rule: str


class Asset(_Contract):
    symbol: str
    asset_class: AssetClass
    price: Price
    changes: Changes
    indicators: Indicators | None = None
    scores: Scores
    market_health_index: int = Field(ge=0, le=100)
    regime_sensitivity: RegimeSensitivity
    activated_rules: list[RuleActivation]
    causal_links: list[CausalLink]
    human_summary_fa: str | None = None
    novelty_flags: list[str] | None = None
    data_gaps: list[str]


class FearGreed(_Contract):
    value: int = Field(ge=0, le=100)
    label: FearGreedLabel


class RecentSurprise(_Contract):
    event: str
    surprise_sigma: float


class ExpectationContext(_Contract):
    recent_surprises: list[RecentSurprise] | None = None


class Global(_Contract):
    fear_greed: FearGreed
    btc_dominance: float = Field(ge=0.0, le=100.0)
    total_market_cap_usd: float = Field(ge=0.0)
    expectation_context: ExpectationContext | None
    onchain_context: None = None


class GuardrailFlag(_Contract):
    code: str
    severity: Severity
    detail: str | None = None
    field: str | None = None


class MarketStateRun(_Contract):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    run_sequence: int = Field(ge=0)
    trigger_type: TriggerType
    trigger_detail: TriggerDetail
    generated_at: str
    is_degraded: bool
    versions: Versions
    regime: Regime
    assets: list[Asset]
    global_: Global = Field(alias="global")
    guardrail_flags: list[GuardrailFlag]
    disclaimer: str

    def to_contract_dict(self) -> dict[str, object]:
        """Serialize with the exact frozen contract field names.

        Required-and-nullable fields (``previous_state``, ``sentiment``, ``expectation_context``,
        ``onchain_context``) are always emitted, as ``null`` when unset. All other optional fields
        are omitted when absent (their schema types are non-nullable, so emitting ``null`` would be
        invalid).
        """
        raw = self.model_dump(by_alias=True)
        return prune_none(raw, _KEEP_NULL_KEYS)  # type: ignore[return-value]


_KEEP_NULL_KEYS = frozenset(
    {"previous_state", "sentiment", "expectation_context", "onchain_context"}
)
