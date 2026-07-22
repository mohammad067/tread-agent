"""Ablation Runner — run pipeline variants over identical inputs for paired comparison (F2).

Supported variants (a subset of the frozen A→D ablation ladder, pipelines.md §5):
  - ``DETERMINISTIC_ONLY`` — no LLM at all (both calls degrade) → a pure rules+scoring run.
  - ``DETERMINISTIC_SENTIMENT`` — sentiment only (synthesis degrades) → scores reflect sentiment.
  - ``FULL`` — both LLM calls succeed → full run with summaries.

Each variant runs the SAME ``IngestBundle`` through the real ``PipelineOrchestrator`` with a variant
``MarketReasoner`` double that returns/omits LLM output per the variant — the deterministic core is
identical across variants, so their deterministic fields are byte-identical by construction (the
ablation's whole point). Produces directly comparable results. No live provider is contacted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from market_state_engine.config.loader import ConfigBundle
from market_state_engine.core.run_context import RunContext
from market_state_engine.evaluation.replay_harness import (
    core_fingerprint,
    deterministic_fingerprint,
)
from market_state_engine.pipeline.orchestrator import IngestBundle, PipelineOrchestrator
from market_state_engine.reasoning.models import (
    DegradedMarker,
    LastAttempt,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)
from market_state_engine.rules.engine import RuleEngine


class AblationVariant(str, Enum):
    DETERMINISTIC_ONLY = "deterministic_only"
    DETERMINISTIC_SENTIMENT = "deterministic_sentiment"
    FULL = "full"


@dataclass(frozen=True)
class VariantResult:
    variant: AblationVariant
    is_degraded: bool
    deterministic_fingerprint: str
    core_fingerprint: str
    run: dict[str, object]


@dataclass(frozen=True)
class AblationComparison:
    results: list[VariantResult]

    @property
    def core_fields_identical(self) -> bool:
        """The sentiment-independent core (regime/trend/risk/rules) is identical across variants."""
        fps = {r.core_fingerprint for r in self.results}
        return len(fps) == 1

    def by_variant(self, variant: AblationVariant) -> VariantResult:
        return next(r for r in self.results if r.variant == variant)


class _VariantReasoner:
    """A ``MarketReasoner`` double emitting sentiment/synthesis per the ablation variant."""

    def __init__(
        self,
        variant: AblationVariant,
        sentiment: SentimentResponse,
        synthesis: SynthesisResponse,
    ) -> None:
        self._variant = variant
        self._sentiment = sentiment
        self._synthesis = synthesis

    def analyze_sentiment(self, request: ReasoningRequest) -> SentimentResponse | DegradedMarker:
        if self._variant is AblationVariant.DETERMINISTIC_ONLY:
            return DegradedMarker(
                job=request.job, reason="ablation:no_llm", last_attempt=_none_attempt()
            )
        return self._sentiment

    def synthesize(self, request: ReasoningRequest) -> SynthesisResponse | DegradedMarker:
        if self._variant is AblationVariant.FULL:
            return self._synthesis
        return DegradedMarker(
            job=request.job, reason="ablation:no_synthesis", last_attempt=_none_attempt()
        )


def _none_attempt() -> LastAttempt:
    return LastAttempt(provider="none", model_id="none")


class AblationRunner:
    def __init__(
        self,
        config: ConfigBundle,
        rules: RuleEngine,
        rulebook_version: str,
        clock: Callable[[], datetime],
        sentiment: SentimentResponse,
        synthesis: SynthesisResponse,
    ) -> None:
        self._config = config
        self._rules = rules
        self._rulebook_version = rulebook_version
        self._clock = clock
        self._sentiment = sentiment
        self._synthesis = synthesis

    def run_variant(
        self, variant: AblationVariant, ctx: RunContext, ingest: IngestBundle
    ) -> VariantResult:
        reasoner = _VariantReasoner(variant, self._sentiment, self._synthesis)
        orchestrator = PipelineOrchestrator(
            config=self._config,
            rules=self._rules,
            reasoner=reasoner,
            rulebook_version=self._rulebook_version,
            clock=self._clock,
        )
        result = orchestrator.run(ctx, ingest)
        doc = result.run.to_contract_dict()
        return VariantResult(
            variant=variant,
            is_degraded=result.is_degraded,
            deterministic_fingerprint=deterministic_fingerprint(doc),
            core_fingerprint=core_fingerprint(doc),
            run=doc,
        )

    def compare(self, ctx: RunContext, ingest: IngestBundle) -> AblationComparison:
        """Run all three variants over identical inputs → directly comparable results."""
        return AblationComparison(
            results=[
                self.run_variant(v, ctx, ingest)
                for v in (
                    AblationVariant.DETERMINISTIC_ONLY,
                    AblationVariant.DETERMINISTIC_SENTIMENT,
                    AblationVariant.FULL,
                )
            ]
        )
