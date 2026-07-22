"""M6 test harness — build stored runs (with/without news) for evaluation + replay + ablation."""

from __future__ import annotations

# Reuse the M5 integration harness (fixed clock, mock ingestion, sequenced fake provider).
import sys
from pathlib import Path

from market_state_engine.app.container import Container, build_container
from market_state_engine.core.enums import RegimeState
from market_state_engine.pipeline.orchestrator import IngestBundle
from market_state_engine.reasoning.adapters.fake import FakeProvider
from market_state_engine.reasoning.errors import ProviderCallError

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:  # pragma: no cover - import wiring
    sys.path.insert(0, str(_TESTS))

from integration._harness import (  # noqa: E402
    REPO,
    SYMBOLS,
    SequencedFake,
    fixed_clock,
    ingest_provider,
    sentiment_text,
    synthesis_text,
)

__all__ = [
    "REPO",
    "SYMBOLS",
    "SequencedFake",
    "build_degraded_container",
    "build_full_container",
    "fixed_clock",
    "ingest_provider",
    "ingest_provider_no_news",
    "sentiment_text",
    "stored_full_run",
    "synthesis_text",
]


def ingest_provider_no_news(ctx: object) -> IngestBundle:
    """Same inputs as the M5 harness but with no news items — so the sentiment prompt (and thus the
    whole LLM leg) is fully reproducible from ``run_inputs`` on replay."""
    base = ingest_provider(ctx)
    return IngestBundle(
        indicator_snapshots=base.indicator_snapshots,
        price_snapshots=base.price_snapshots,
        global_snapshots=base.global_snapshots,
        events=base.events,
        news_items=[],
    )


def build_full_container(*, no_news: bool = False) -> Container:
    provider = ingest_provider_no_news if no_news else ingest_provider
    return build_container(
        REPO,
        env="dev",
        ingest_provider=provider,
        overrides={"openai": SequencedFake("openai")},
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )


def build_degraded_container() -> Container:
    return build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides={
            "openai": FakeProvider(name="openai", raise_exc=ProviderCallError("down")),
            "anthropic": FakeProvider(name="anthropic", raise_exc=ProviderCallError("down")),
        },
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )


def stored_full_run(run_id: str, *, no_news: bool = False) -> Container:
    """Build a container and persist one full run under ``run_id``; return the container."""
    c = build_full_container(no_news=no_news)
    c.scheduler.run_manual(run_id=run_id)
    return c
