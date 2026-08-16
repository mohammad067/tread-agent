"""Assemble a complete deterministic MarketStateRun (a degraded run when no LLM is available).

Pure composition of the deterministic core's outputs into the frozen public contract. LLM-produced
fields (sentiment, human_summary_fa, novelty_flags, ordinal drivers) are omitted/null,
``is_degraded`` is true, and a ``degraded_run`` guardrail flag is emitted (ADR-011). The result
validates against schemas/market_state_run.v1.0.0.json.
"""

from __future__ import annotations

from market_state_engine.config.loader import ConfigBundle
from market_state_engine.core.dtos import FeatureSet, RawSnapshot
from market_state_engine.core.enums import (
    AssetClass,
    Currency,
    Direction,
    FearGreedLabel,
    OrdinalLevel,
    RegimeSensitivity,
    RegimeState,
    Severity,
    TriggerType,
)
from market_state_engine.core.models import (
    Asset,
    CausalLink,
    Changes,
    Driver,
    ExpectationContext,
    FearGreed,
    Global,
    GuardrailFlag,
    Indicators,
    MarketStateRun,
    Price,
    RecentSurprise,
    Regime,
    RuleActivation,
    Scores,
    TriggerDetail,
    Versions,
)
from market_state_engine.core.run_context import RunContext
from market_state_engine.guardrails.engine import validate
from market_state_engine.rules.engine import Activation
from market_state_engine.scoring.engine import ScoringResult

_DISCLAIMER = (
    "This is a market observation, not investment advice. Confidence values are system confidence, "
    "not calibrated probabilities."
)

# Deterministic placeholders for artifact versions not yet wired (LLM/pipeline arrive in M4/M5).
_DEGRADED_VERSION_PLACEHOLDERS = {
    "prompt_sentiment": "none",
    "prompt_synthesis": "none",
    "provider": "none",
    "model": "none",
    "pipeline": "0.0.0",
    "pricing": "none",
}


class DeterministicStateAssembler:
    def __init__(self, config: ConfigBundle, rulebook_version: str) -> None:
        self._config = config
        self._rulebook_version = rulebook_version

    def assemble(
        self,
        ctx: RunContext,
        feature_set: FeatureSet,
        scoring: ScoringResult,
        activations: dict[str, list[Activation]],
        conflict_flags: list[GuardrailFlag],
        price_snapshots: dict[str, RawSnapshot],
        global_snapshots: dict[str, RawSnapshot],
    ) -> MarketStateRun:
        assets = [
            self._asset(symbol, feature_set, scoring, activations, price_snapshots)
            for symbol in self._config.assets
            if symbol in scoring.per_asset
        ]

        run = MarketStateRun(
            run_id=ctx.run_id,
            run_sequence=ctx.run_sequence,
            trigger_type=ctx.trigger_type,
            trigger_detail=self._trigger_detail(ctx),
            generated_at=ctx.now.isoformat().replace("+00:00", "Z"),
            is_degraded=True,
            versions=self._versions(),
            regime=self._regime(scoring),
            assets=assets,
            **{"global": self._global(feature_set, global_snapshots)},  # type: ignore[arg-type]
            guardrail_flags=[
                GuardrailFlag(
                    code="degraded_run",
                    severity=Severity.WARNING,
                    detail=(
                        "No LLM provider available; sentiment and human summaries omitted. "
                        "Deterministic outputs intact."
                    ),
                ),
                *conflict_flags,
            ],
            disclaimer=_DISCLAIMER,
        )

        result = validate(run)
        # Re-attach any additional flags the guardrails produced (publish-with-flags policy).
        if result.flags != run.guardrail_flags:
            run = run.model_copy(update={"guardrail_flags": result.flags})
        return run

    def _trigger_detail(self, ctx: RunContext) -> TriggerDetail:
        if ctx.trigger_type is TriggerType.SCHEDULED:
            return TriggerDetail(scheduled_for=ctx.now.isoformat().replace("+00:00", "Z"))
        return TriggerDetail(debounced_events=0)

    def _versions(self) -> Versions:
        return Versions(
            rulebook=self._rulebook_version,
            mhi_weights=self._config.mhi_weights.version,
            **_DEGRADED_VERSION_PLACEHOLDERS,
        )

    def _regime(self, scoring: ScoringResult) -> Regime:
        r = scoring.regime
        drivers = [Driver.model_validate(d) for d in r.computed_drivers]
        return Regime(
            state=RegimeState(r.state),
            previous_state=(
                RegimeState(r.previous_state) if r.previous_state is not None else None
            ),
            changed_this_run=r.changed_this_run,
            confidence=r.confidence,
            drivers=drivers,
        )

    def _asset(
        self,
        symbol: str,
        feature_set: FeatureSet,
        scoring: ScoringResult,
        activations: dict[str, list[Activation]],
        price_snapshots: dict[str, RawSnapshot],
    ) -> Asset:
        cfg = self._config.assets[symbol]
        features = feature_set.per_asset[symbol]
        scored = scoring.per_asset[symbol]

        acts = activations.get(symbol, [])
        rule_activations = [
            RuleActivation(
                rule_id=a.rule_id,
                strength=_ordinal(a.strength),
                horizon=a.horizon,
                decay_remaining=a.decay_remaining,
            )
            for a in acts
        ]
        causal_links = [
            CausalLink.model_validate(
                {
                    "from": a.event_id if a.event_id is not None else a.rule_id,
                    "to": symbol,
                    "direction": a.direction,
                    "via_rule": a.rule_id,
                }
            )
            for a in acts
            if a.direction != Direction.NEUTRAL.value
        ]

        return Asset(
            symbol=symbol,
            asset_class=AssetClass(cfg.asset_class.value),
            price=self._price(symbol, price_snapshots),
            changes=Changes.model_validate(
                {
                    "6h": _num(features.changes.h6),
                    "24h": _num(features.changes.h24),
                    "7d": _num(features.changes.d7),
                    "30d": _num(features.changes.d30),
                }
            ),
            indicators=(
                Indicators.model_validate(features.indicators) if features.indicators else None
            ),
            scores=Scores(
                trend=scored.scores.trend,
                risk=scored.scores.risk,
                sentiment=None,  # degraded: honest absence
                confidence=scored.scores.confidence,
            ),
            market_health_index=scored.market_health_index,
            regime_sensitivity=RegimeSensitivity(cfg.regime_sensitivity.value),
            activated_rules=rule_activations,
            causal_links=causal_links,
            data_gaps=_data_gaps(symbol, features),
        )

    def _price(
        self,
        symbol: str,
        price_snapshots: dict[str, RawSnapshot],
    ) -> Price:
        snap = price_snapshots.get(symbol)
        currency = Currency.IRT if symbol == "USD_IRR" else Currency.USD
        if snap is None:
            # No price snapshot: emit a stale placeholder so the run still validates + degrades.
            return Price(
                value=0.0,
                currency=currency,
                as_of="1970-01-01T00:00:00Z",
                is_stale=True,
                stale_reason="price_unavailable",
            )
        value = _as_float(snap.payload.get("value"), 0.0)
        return Price(
            value=value,
            currency=currency,
            as_of=snap.as_of,
            is_stale=snap.is_stale,
            stale_reason=snap.stale_reason,
        )

    def _global(
        self,
        feature_set: FeatureSet,
        global_snapshots: dict[str, RawSnapshot],
    ) -> Global:
        gf = feature_set.global_features
        fg_value = int(_as_float(gf.get("fear_greed_value"), 50.0))
        recent = [
            RecentSurprise(event=e.event_id, surprise_sigma=(e.surprise_sigma or e.surprise))
            for e in feature_set.event_features
        ]
        return Global(
            fear_greed=FearGreed(value=fg_value, label=_fg_label(fg_value)),
            btc_dominance=_as_float(gf.get("btc_dominance"), 0.0),
            total_market_cap_usd=_as_float(gf.get("total_market_cap_usd"), 0.0),
            expectation_context=ExpectationContext(recent_surprises=recent),
            onchain_context=None,
        )


def _num(value: float | None) -> float:
    return value if value is not None else 0.0


def _as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _ordinal(value: str) -> OrdinalLevel:
    return OrdinalLevel(value)


def _fg_label(value: int) -> FearGreedLabel:
    if value <= 24:
        return FearGreedLabel.EXTREME_FEAR
    if value <= 44:
        return FearGreedLabel.FEAR
    if value <= 55:
        return FearGreedLabel.NEUTRAL
    if value <= 74:
        return FearGreedLabel.GREED
    return FearGreedLabel.EXTREME_GREED


def _data_gaps(symbol: str, features: object) -> list[str]:
    gaps: list[str] = []
    f = features  # AssetFeatures
    if f.changes.h6 is None:  # type: ignore[attr-defined]
        gaps.append("missing_6h_change")
    if symbol == "TOTAL_MCAP":
        if f.changes.h24 is None:  # type: ignore[attr-defined]
            gaps.append("missing_24h_change")
        if f.changes.d7 is None:  # type: ignore[attr-defined]
            gaps.append("missing_7d_change")
        if f.changes.d30 is None:  # type: ignore[attr-defined]
            gaps.append("missing_30d_change")
    return gaps
