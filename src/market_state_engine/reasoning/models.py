"""Reasoning DTOs — Pydantic mirrors of the frozen internal schemas.

Mirror, byte-faithful, of:
  - reasoning_request.v1.json   -> ReasoningRequest
  - reasoning_response.v1.json  -> SentimentResponse | SynthesisResponse
  - degraded_marker.v1.json     -> DegradedMarker
  - call_record.v1.json         -> CallRecord

``extra="forbid"`` matches ``additionalProperties: false`` in every schema. ``to_contract_dict``
emits a dict that validates against the corresponding schema (None-pruning where a field is
optional-non-nullable; required-nullable fields are retained explicitly).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from market_state_engine.core.enums import LlmJob
from market_state_engine.core.serialization import prune_none


class _Dto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- ReasoningRequest (reasoning_request.v1.json) --------------------------------------
class RequestConstraints(_Dto):
    language: str = "fa"
    grounding: bool
    output_schema_ref: str
    max_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0.0)


class SelfConsistency(_Dto):
    enabled: bool
    samples: int = Field(ge=1)


class ReasoningRequest(_Dto):
    run_id: str
    job: LlmJob
    payload: dict[str, object]
    constraints: RequestConstraints
    self_consistency: SelfConsistency | None = None

    def to_contract_dict(self) -> dict[str, object]:
        raw = self.model_dump(by_alias=True)
        return prune_none(raw)  # type: ignore[return-value]


# --- ReasoningResponse (reasoning_response.v1.json) ------------------------------------
class SentimentResponse(_Dto):
    per_asset_sentiment: dict[str, float]
    global_sentiment: float = Field(ge=-1.0, le=1.0)
    confidence_signals: dict[str, object] | None = None

    def to_contract_dict(self) -> dict[str, object]:
        return prune_none(self.model_dump(by_alias=True))  # type: ignore[return-value]


class OrdinalDriver(_Dto):
    name: str
    weight_type: str = "ordinal"
    level: str
    detail: str | None = None


class SynthesisAsset(_Dto):
    human_summary_fa: str
    ordinal_drivers: list[OrdinalDriver]
    novelty_flags: list[str]
    data_gap_notes: list[str]


class SynthesisResponse(_Dto):
    per_asset: dict[str, SynthesisAsset]
    grounding_ok: bool | None = None

    def to_contract_dict(self) -> dict[str, object]:
        return prune_none(self.model_dump(by_alias=True))  # type: ignore[return-value]


# --- DegradedMarker (degraded_marker.v1.json) ------------------------------------------
class LastAttempt(_Dto):
    provider: str
    model_id: str


class DegradedMarker(_Dto):
    job: LlmJob
    reason: str
    last_attempt: LastAttempt

    def to_contract_dict(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)


# --- CallRecord (call_record.v1.json) --------------------------------------------------
class CallRecord(_Dto):
    run_id: str
    llm_job: LlmJob
    attempt_index: int = Field(ge=0)
    provider: str
    model_id: str
    prompt_version: str
    prompt_hash: str
    rendered_prompt: str
    response: dict[str, object] | None
    response_hash: str | None
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0.0)
    retries: int = Field(ge=0)
    finish_reason: str | None
    outcome: str
    created_at: str

    def to_contract_dict(self) -> dict[str, object]:
        # response/response_hash/token/cost/finish_reason are required-nullable in the schema —
        # keep them (even as null); nothing else needs pruning.
        return self.model_dump(by_alias=True)
