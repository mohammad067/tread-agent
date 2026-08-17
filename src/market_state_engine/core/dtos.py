"""Internal DTOs that cross module boundaries. Mirror schemas/internal/*.v1.json.

Pure Pydantic models; no I/O. These are the replay-critical contracts between the deterministic
components (ingestion -> features -> rules/scoring -> news) and, later, the reasoning port.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import EventType
from .serialization import prune_none

# Required-and-nullable keys in feature_set.v1.json: the change horizons (a missing horizon is an
# explicit null) and event_features[].surprise_sigma. Retained even when None.
_FEATURE_SET_KEEP_NULL = ("6h", "24h", "7d", "30d", "surprise_sigma")


class _Dto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- RawSnapshot (raw_snapshot.v1.json) ------------------------------------------------
class RawSnapshot(_Dto):
    source_id: str
    symbol: str | None
    payload: dict[str, object]
    as_of: str
    is_stale: bool
    stale_reason: str | None = None
    deviation_flags: list[dict[str, object]]
    content_hash: str


class TotalMcapSample(_Dto):
    """One persisted TOTAL_MCAP observation used only for historical horizons."""

    symbol: str
    value: float = Field(gt=0.0)
    as_of: str
    run_id: str | None = None


# --- FeatureSet (feature_set.v1.json) --------------------------------------------------
class AssetChanges(_Dto):
    h6: float | None = Field(alias="6h")
    h24: float | None = Field(alias="24h")
    d7: float | None = Field(alias="7d")
    d30: float | None = Field(alias="30d")


class AssetFeatures(_Dto):
    indicators: dict[str, object] | None = None
    changes: AssetChanges
    atr_pct: float | None = Field(default=None, ge=0.0)
    volume_ratio_20d: float | None = Field(default=None, ge=0.0)
    event_proximity: float | None = None
    decay_inputs: dict[str, object] | None = None


class EventFeature(_Dto):
    event_id: str
    event_type: str
    surprise: float
    surprise_sigma: float | None
    proximity_hours: float


class FeatureSet(_Dto):
    run_id: str
    per_asset: dict[str, AssetFeatures]
    global_features: dict[str, object]
    event_features: list[EventFeature]
    news_features: dict[str, object]
    config_versions: dict[str, object]

    def to_contract_dict(self) -> dict[str, object]:
        raw = self.model_dump(by_alias=True)
        return prune_none(raw, _FEATURE_SET_KEEP_NULL)  # type: ignore[return-value]


# --- NewsDigest (news_digest.v3.json) --------------------------------------------------
class AssetNewsWeight(_Dto):
    relevance: float = Field(ge=0.0, le=1.0)
    effective_weight: float = Field(ge=0.0, le=1.0)


class WeightedNewsItem(_Dto):
    news_id: str
    title: str
    evidence_text: str = Field(max_length=2000)
    source: str
    published_at: str
    source_quality: float = Field(ge=0.0, le=1.0)
    recency_decay: float = Field(ge=0.0, le=1.0)
    asset_weights: dict[str, AssetNewsWeight]
    max_effective_weight: float = Field(ge=0.0, le=1.0)


class NewsDigest(_Dto):
    run_id: str
    items: list[WeightedNewsItem]
    weighting_versions: dict[str, object]

    def to_contract_dict(self) -> dict[str, object]:
        # All NewsDigest fields are required; no None-pruning needed.
        return self.model_dump(by_alias=True)


# --- Scored per-asset outputs (deterministic core; feed assembly) ----------------------
class AssetScores(_Dto):
    trend: float = Field(ge=-1.0, le=1.0)
    risk: float = Field(ge=0.0, le=1.0)
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class RegimeResult(_Dto):
    state: str
    previous_state: str | None
    changed_this_run: bool
    confidence: float = Field(ge=0.0, le=1.0)
    computed_drivers: list[dict[str, object]]


# --- Raw input records (fed by ingestion; used by features) ----------------------------
class NewsItem(_Dto):
    """A pre-collected news record consumed from the external feed (Q3)."""

    news_id: str
    title: str
    source: str
    published_at: str
    body: str | None = None
    asset_tags: list[str] | None = None
    relevance: float | None = Field(default=None, ge=0.0, le=1.0)


class MacroEvent(_Dto):
    """A manually entered macro event (Q4). Surprise is computed in code, never trusted."""

    event_id: str
    event_type: EventType
    scheduled_at: str
    consensus: float
    actual: float | None = None
