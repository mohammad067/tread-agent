"""Rule domain models mirroring schemas/internal/rule.v1.json. Pure Pydantic."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from market_state_engine.core.enums import Direction, EventType, OrdinalLevel, RegimeState


class _RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(_RuleModel):
    event_type: EventType | None = None
    condition: str = Field(min_length=1)
    condition_vars: list[str]


class Effect(_RuleModel):
    asset: str
    direction: Direction
    strength: OrdinalLevel
    horizon: str
    uncertain: bool | None = None


class RegimeGuard(_RuleModel):
    applies_in: list[RegimeState]
    else_: str = Field(alias="else")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Rule(_RuleModel):
    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: str
    trigger: Trigger
    effects: list[Effect] = Field(min_length=1)
    regime_guard: RegimeGuard | None = None
    half_life_hours: float = Field(gt=0.0)
    source: str = Field(min_length=1)
    economic_rationale: str = Field(min_length=1)
    reviewed_by: str
    reviewed_at: str
