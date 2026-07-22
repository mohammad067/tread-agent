"""Ablation Runner tests (M6): deterministic-only / +sentiment / full variants, comparable."""

from __future__ import annotations

import json

from market_state_engine.config.loader import load_config_bundle
from market_state_engine.core.enums import RegimeState, TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.evaluation.ablation import AblationRunner, AblationVariant
from market_state_engine.reasoning.models import SentimentResponse, SynthesisResponse
from market_state_engine.rules.engine import RuleEngine
from market_state_engine.rules.loader import load_rulebook, read_rulebook_version

from ._m6_harness import REPO, SYMBOLS, fixed_clock, ingest_provider


def _runner() -> AblationRunner:
    config = load_config_bundle(REPO / "config")
    rules_dir = REPO / "rules"
    sentiment = SentimentResponse.model_validate(json.loads(_sentiment_json()))
    synthesis = SynthesisResponse.model_validate(json.loads(_synthesis_json()))
    return AblationRunner(
        config=config,
        rules=RuleEngine(load_rulebook(rules_dir)),
        rulebook_version=read_rulebook_version(rules_dir),
        clock=fixed_clock,
        sentiment=sentiment,
        synthesis=synthesis,
    )


def _sentiment_json() -> str:
    return json.dumps(
        {"per_asset_sentiment": {s: -0.2 for s in SYMBOLS}, "global_sentiment": -0.25}
    )


def _synthesis_json() -> str:
    return json.dumps(
        {
            "per_asset": {
                s: {
                    "human_summary_fa": "خلاصه",
                    "ordinal_drivers": [
                        {"name": "cpi", "weight_type": "ordinal", "level": "major"}
                    ],
                    "novelty_flags": [],
                    "data_gap_notes": [],
                }
                for s in SYMBOLS
            },
            "grounding_ok": True,
        }
    )


def _ctx() -> RunContext:
    return RunContext(
        run_id="ABLATION0000000000000000AB",
        run_sequence=1,
        trigger_type=TriggerType.EVENT,
        now=fixed_clock(),
        previous_state=RegimeState.TRANSITION,
        versions={},
    )


def test_three_variants_run() -> None:
    comparison = _runner().compare(_ctx(), ingest_provider(None))
    variants = {r.variant for r in comparison.results}
    assert variants == {
        AblationVariant.DETERMINISTIC_ONLY,
        AblationVariant.DETERMINISTIC_SENTIMENT,
        AblationVariant.FULL,
    }


def test_deterministic_only_is_degraded_and_no_sentiment() -> None:
    comparison = _runner().compare(_ctx(), ingest_provider(None))
    det = comparison.by_variant(AblationVariant.DETERMINISTIC_ONLY)
    assert det.is_degraded is True
    btc = next(a for a in det.run["assets"] if a["symbol"] == "BTC")
    assert btc["scores"]["sentiment"] is None


def test_full_variant_has_sentiment_and_summary() -> None:
    comparison = _runner().compare(_ctx(), ingest_provider(None))
    full = comparison.by_variant(AblationVariant.FULL)
    assert full.is_degraded is False
    btc = next(a for a in full.run["assets"] if a["symbol"] == "BTC")
    assert btc["scores"]["sentiment"] == -0.2
    assert "human_summary_fa" in btc


def test_core_fields_identical_across_variants() -> None:
    # The sentiment-independent core (regime/trend/risk/rules) is identical across all variants —
    # the ablation's whole point: only the LLM-fed layer changes.
    comparison = _runner().compare(_ctx(), ingest_provider(None))
    assert comparison.core_fields_identical is True


def test_sentiment_variant_differs_from_deterministic_only_on_mhi() -> None:
    # MHI legitimately folds in sentiment, so +sentiment differs from deterministic-only on the FULL
    # fingerprint even though the core matches.
    comparison = _runner().compare(_ctx(), ingest_provider(None))
    det = comparison.by_variant(AblationVariant.DETERMINISTIC_ONLY)
    sent = comparison.by_variant(AblationVariant.DETERMINISTIC_SENTIMENT)
    assert det.core_fingerprint == sent.core_fingerprint
    assert det.deterministic_fingerprint != sent.deterministic_fingerprint
