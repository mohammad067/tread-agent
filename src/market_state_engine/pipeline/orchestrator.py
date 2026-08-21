"""Pipeline Orchestrator — sequences the frozen 10-stage Market State lifecycle (pipelines.md §2).

Connects existing components in the deterministic-first order; the LLM appears at two stages,
both via the ``MarketReasoner`` port:

  1 trigger → 2 ingest → 3 features → 4 rule match → 5 sentiment (LLM #1) → 6 scoring/regime →
  7 synthesis (LLM #2) → 8 guardrails → 9 persist/publish.

The deterministic core owns every number; this layer computes none. It builds the neutral
``ReasoningRequest``s, applies returned sentiment into scoring, enriches the assembled run with
synthesis output (via ``model_copy`` — the deterministic assembler is never modified), and persists
inputs/output/call-records/activations. A provider outage yields honest absence and never aborts
(ADR-011); persistence records every attempt and every lifecycle event.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from ulid import ULID

from market_state_engine.assembly.deterministic_state import DeterministicStateAssembler
from market_state_engine.config.loader import ConfigBundle
from market_state_engine.core.dtos import MacroEvent, NewsDigest, NewsItem, RawSnapshot
from market_state_engine.core.enums import RegimeState, Severity, TriggerType
from market_state_engine.core.models import GuardrailFlag, MarketStateRun, Scores
from market_state_engine.core.run_context import RunContext
from market_state_engine.features.engine import FeatureEngine
from market_state_engine.guardrails.engine import validate as guardrail_validate
from market_state_engine.news.weigher import NewsWeigher
from market_state_engine.reasoning.models import (
    DegradedMarker,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)
from market_state_engine.reasoning.port import MarketReasoner
from market_state_engine.rules.engine import RuleEngine
from market_state_engine.scoring.engine import ScoringEngine

_PIPELINE_VERSION = "1.2.0"


@dataclass(frozen=True)
class IngestBundle:
    """Raw snapshots + events + news an ingestion adapter provides for one run (already fetched)."""

    indicator_snapshots: dict[str, RawSnapshot]
    price_snapshots: dict[str, RawSnapshot]
    global_snapshots: dict[str, RawSnapshot]
    events: list[MacroEvent]
    news_items: list[NewsItem] = field(default_factory=list)


@dataclass
class PipelineResult:
    run: MarketStateRun
    is_degraded: bool = True
    published: bool = True


class PipelineOrchestrator:
    def __init__(
        self,
        config: ConfigBundle,
        rules: RuleEngine,
        reasoner: MarketReasoner,
        rulebook_version: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._rules = rules
        self._reasoner = reasoner
        self._rulebook_version = rulebook_version
        self._clock = clock
        self._features = FeatureEngine(config)
        self._scoring = ScoringEngine(config)
        self._weigher = NewsWeigher(config.source_quality, config.half_lives)
        self._assembler = DeterministicStateAssembler(config, rulebook_version)

    def run(self, ctx: RunContext, ingest: IngestBundle) -> PipelineResult:
        # 3 Feature computation (deterministic).
        features = self._features.compute(
            ingest.price_snapshots,
            ingest.indicator_snapshots,
            ingest.global_snapshots,
            ingest.events,
            ctx,
        )

        # News weighting (deterministic F-6): effective_weight per item, ranked into a NewsDigest.
        digest = self._weigher.weigh(
            ctx.run_id, ingest.news_items, set(self._config.assets.keys()), ctx.now
        )

        # 5 Conditional LLM Call #1. No eligible evidence is a normal skip, not degradation.
        sentiment_assets = _digest_assets(digest)
        sentiment_resp = self._sentiment(ctx, digest, sentiment_assets)
        sentiment_failed = bool(sentiment_assets) and sentiment_resp is None
        sentiment_map = _sentiment_map(sentiment_resp)

        # 6 Deterministic scoring + regime (regime computed among the market outputs here).
        scoring = self._scoring.score(features, ctx.previous_state, sentiment=sentiment_map)
        regime_state = RegimeState(scoring.regime.state)

        # 4/6b Rule matching (regime-guarded rules resolved now that regime is known).
        activations, conflict_findings = self._rules.match(features.event_features, regime_state)
        conflict_flags = [
            GuardrailFlag(
                code="rule_conflict", severity=Severity.WARNING, detail=f.detail, field=None
            )
            for f in conflict_findings
        ]

        # 9 (assembly) Deterministic base run (degraded shape — LLM fields absent by construction).
        base = self._assembler.assemble(
            ctx,
            features,
            scoring,
            activations,
            conflict_flags,
            ingest.price_snapshots,
            ingest.global_snapshots,
        )

        # 7 LLM Call #2 — Synthesis (narrates the finished state). Honest absence on failure.
        synthesis_resp = self._synthesis(ctx, base, sentiment_resp)
        synthesis_failed = synthesis_resp is None

        # Compose the LLM output into the run WITHOUT touching the deterministic core.
        run = _compose(
            base,
            sentiment_map,
            synthesis_resp,
            sentiment_failed=sentiment_failed,
            synthesis_failed=synthesis_failed,
        )

        # 8 Guardrails (deterministic post-validation; publish-with-flags).
        guardrail = guardrail_validate(run)
        if guardrail.flags != run.guardrail_flags:
            run = run.model_copy(update={"guardrail_flags": guardrail.flags})

        return PipelineResult(
            run=run,
            is_degraded=run.is_degraded,
            published=guardrail.publish,
        )

    # --- LLM stages ---------------------------------------------------------------------
    def _sentiment(
        self,
        ctx: RunContext,
        digest: NewsDigest,
        evidence_assets: list[str],
    ) -> SentimentResponse | None:
        if not evidence_assets:
            return None

        request = ReasoningRequest.model_validate(
            {
                "run_id": ctx.run_id,
                "job": "sentiment",
                "payload": {
                    "assets": evidence_assets,
                    "news_digest": digest.to_contract_dict(),
                },
                "constraints": {
                    "language": "fa",
                    "grounding": True,
                    "output_schema_ref": "reasoning_response.v1.json#/$defs/SentimentResponse",
                    "max_tokens": 512,
                    "temperature": 0,
                },
            }
        )
        result = self._reasoner.analyze_sentiment(request)
        if isinstance(result, DegradedMarker):
            return None
        allowed = set(evidence_assets)
        filtered = {
            asset: value for asset, value in result.per_asset_sentiment.items() if asset in allowed
        }
        return result.model_copy(update={"per_asset_sentiment": filtered})

    def _synthesis(
        self, ctx: RunContext, base: MarketStateRun, sentiment: SentimentResponse | None
    ) -> SynthesisResponse | None:
        request = ReasoningRequest.model_validate(
            {
                "run_id": ctx.run_id,
                "job": "synthesis",
                "payload": {
                    "state_vector": _state_vector(base),
                    "sentiment": (sentiment.to_contract_dict() if sentiment is not None else {}),
                },
                "constraints": {
                    "language": "fa",
                    "grounding": True,
                    "output_schema_ref": "reasoning_response.v1.json#/$defs/SynthesisResponse",
                    "max_tokens": 1024,
                    "temperature": 0,
                },
            }
        )
        result = self._reasoner.synthesize(request)
        if isinstance(result, DegradedMarker):
            return None
        return result


# --- pure composition helpers (no market math) ---------------------------------------
def _sentiment_map(resp: SentimentResponse | None) -> dict[str, float] | None:
    if resp is None:
        return None
    return dict(resp.per_asset_sentiment)


def _digest_assets(digest: NewsDigest) -> list[str]:
    return sorted({asset for item in digest.items for asset in item.asset_weights})


def _state_vector(run: MarketStateRun) -> dict[str, object]:
    doc = run.to_contract_dict()
    per_asset: dict[str, object] = {}
    assets = doc.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        a = dict(asset) if isinstance(asset, dict) else {}
        per_asset[str(a["symbol"])] = {
            "scores": a["scores"],
            "market_health_index": a["market_health_index"],
        }
    return {
        "run_id": doc["run_id"],
        "regime": doc["regime"],
        "per_asset": per_asset,
    }


def _compose(
    base: MarketStateRun,
    sentiment: dict[str, float] | None,
    synthesis: SynthesisResponse | None,
    *,
    sentiment_failed: bool,
    synthesis_failed: bool,
) -> MarketStateRun:
    """Fold LLM output into the run without recomputing a number (deterministic core untouched)."""
    per_asset_syn = synthesis.per_asset if synthesis is not None else {}
    new_assets = []
    for asset in base.assets:
        updates: dict[str, object] = {}
        if sentiment is not None and asset.symbol in sentiment:
            updates["scores"] = _with_sentiment(asset.scores, sentiment[asset.symbol])
        syn = per_asset_syn.get(asset.symbol)
        if syn is not None:
            updates["human_summary_fa"] = syn.human_summary_fa
            updates["novelty_flags"] = list(syn.novelty_flags)
        new_assets.append(asset.model_copy(update=updates) if updates else asset)

    is_degraded = sentiment_failed or synthesis_failed
    flags = [flag for flag in base.guardrail_flags if flag.code != "degraded_run"]
    if is_degraded:
        flags.append(
            GuardrailFlag(
                code="degraded_run",
                severity=Severity.WARNING,
                detail="One or more attempted LLM jobs exhausted all configured providers.",
            )
        )
    if sentiment_failed:
        flags.append(
            GuardrailFlag(
                code="sentiment_degraded",
                severity=Severity.WARNING,
                detail="Sentiment providers were exhausted; sentiment remains absent.",
            )
        )
    if synthesis_failed:
        flags.append(
            GuardrailFlag(
                code="synthesis_degraded",
                severity=Severity.WARNING,
                detail="Synthesis providers were exhausted; summaries remain absent.",
            )
        )
    return base.model_copy(
        update={"assets": new_assets, "is_degraded": is_degraded, "guardrail_flags": flags}
    )


def _with_sentiment(scores: Scores, value: float) -> Scores:
    return scores.model_copy(update={"sentiment": value})


def new_run_id() -> str:
    """Generate a fresh ULID run id (used by the scheduler when none is supplied)."""
    return str(ULID())


def default_run_context(
    run_id: str,
    run_sequence: int,
    trigger_type: TriggerType,
    now: datetime,
    previous_state: RegimeState | None,
    versions: dict[str, str],
) -> RunContext:
    return RunContext(
        run_id=run_id,
        run_sequence=run_sequence,
        trigger_type=trigger_type,
        now=now,
        previous_state=previous_state,
        versions=versions,
    )
