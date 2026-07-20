"""Deterministic conflict resolution (OQ-3).

Policy (approved): when two active effects target the same asset with opposing directions,
**highest strength wins**. If strengths are equal and directions conflict, resolve to **neutral**
and emit a guardrail flag. Same-direction effects on an asset keep the strongest.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_state_engine.core.enums import Direction, OrdinalLevel

from .models import Effect

_STRENGTH_RANK = {
    OrdinalLevel.MINOR: 1,
    OrdinalLevel.MODERATE: 2,
    OrdinalLevel.MAJOR: 3,
    OrdinalLevel.DOMINANT: 4,
}


@dataclass(frozen=True)
class ResolvedEffect:
    asset: str
    direction: Direction
    strength: OrdinalLevel
    horizon: str
    uncertain: bool
    source_rule_id: str


@dataclass(frozen=True)
class ConflictFlag:
    asset: str
    detail: str


@dataclass(frozen=True)
class ConflictResolution:
    effects: list[ResolvedEffect]
    flags: list[ConflictFlag]


def resolve_asset_effects(
    asset: str, candidates: list[tuple[Effect, str]]
) -> tuple[ResolvedEffect | None, ConflictFlag | None]:
    """Resolve all candidate (effect, rule_id) for one asset into a single ResolvedEffect."""
    if not candidates:
        return None, None
    # Winner by strength, then deterministic tie-break by rule_id.
    winner_eff, winner_rule = max(candidates, key=lambda c: (_STRENGTH_RANK[c[0].strength], c[1]))
    directions = {eff.direction for eff, _ in candidates}
    non_neutral = {d for d in directions if d is not Direction.NEUTRAL}

    if len(non_neutral) <= 1:
        # No opposing directions; keep the strongest.
        return (
            ResolvedEffect(
                asset=asset,
                direction=winner_eff.direction,
                strength=winner_eff.strength,
                horizon=winner_eff.horizon,
                uncertain=bool(winner_eff.uncertain),
                source_rule_id=winner_rule,
            ),
            None,
        )

    # Opposing directions present. Highest strength wins unless there is a strength tie at the top.
    top_rank = _STRENGTH_RANK[winner_eff.strength]
    top_dirs = {
        eff.direction
        for eff, _ in candidates
        if _STRENGTH_RANK[eff.strength] == top_rank and eff.direction is not Direction.NEUTRAL
    }
    if len(top_dirs) > 1:
        flag = ConflictFlag(
            asset=asset,
            detail=(
                f"Opposing effects of equal strength on {asset} "
                f"({', '.join(sorted(d.value for d in top_dirs))}) resolved to neutral."
            ),
        )
        return (
            ResolvedEffect(
                asset=asset,
                direction=Direction.NEUTRAL,
                strength=winner_eff.strength,
                horizon=winner_eff.horizon,
                uncertain=True,
                source_rule_id=winner_rule,
            ),
            flag,
        )

    return (
        ResolvedEffect(
            asset=asset,
            direction=winner_eff.direction,
            strength=winner_eff.strength,
            horizon=winner_eff.horizon,
            uncertain=bool(winner_eff.uncertain),
            source_rule_id=winner_rule,
        ),
        None,
    )
