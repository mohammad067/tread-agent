"""Shared M5 integration harness — build a fully-wired container over an in-memory DB, offline.

Deterministic clock, mock ingestion, and injected provider doubles (never a live vendor). Used by
the pipeline/scheduler/API/replay/persistence/degraded test modules.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from market_state_engine.app.container import Container, build_container
from market_state_engine.core.dtos import MacroEvent, NewsItem
from market_state_engine.core.enums import EventType, RegimeState
from market_state_engine.ingestion.mocks.mock_sources import (
    MockDominanceSource,
    MockFearGreedSource,
    MockIndicatorInputSource,
    MockPriceSource,
    MockTotalMcapSource,
)
from market_state_engine.pipeline.orchestrator import IngestBundle
from market_state_engine.reasoning.adapters.fake import FakeProvider
from market_state_engine.reasoning.types import RawProviderResult

REPO = Path(__file__).resolve().parents[2]
SYMBOLS = ["BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"]


def fixed_clock() -> datetime:
    return datetime(2026, 7, 14, 12, 47, 3, tzinfo=timezone.utc)


def _series(base: float, n: int = 130) -> dict[str, object]:
    closes = [base - 0.5 * i + 2.0 * math.sin(i / 3.0) for i in range(n)]
    return {
        "as_of": "2026-07-14T12:45:00Z",
        "value": closes[-1],
        "closes": closes,
        "highs": [c + 3.0 for c in closes],
        "lows": [c - 3.0 for c in closes],
        "volumes": [1000.0 + 40.0 * i for i in range(n)],
    }


def ingest_provider(ctx: object) -> IngestBundle:
    series = {s: _series(120.0 + i * 10) for i, s in enumerate(SYMBOLS)}
    ind = MockIndicatorInputSource(series)
    price = MockPriceSource(series)
    return IngestBundle(
        indicator_snapshots={s: ind.fetch_series(s, ctx) for s in SYMBOLS},  # type: ignore[arg-type]
        price_snapshots={s: price.fetch(s, ctx) for s in SYMBOLS},  # type: ignore[arg-type]
        global_snapshots={
            "fear_greed": MockFearGreedSource(24, "2026-07-14T12:45:00Z").fetch(ctx),  # type: ignore[arg-type]
            "dominance": MockDominanceSource(56.8, "2026-07-14T12:45:00Z").fetch(ctx),  # type: ignore[arg-type]
            "total_mcap": MockTotalMcapSource(3.91e12, "2026-07-14T12:45:00Z").fetch(ctx),  # type: ignore[arg-type]
        },
        events=[
            MacroEvent(
                event_id="us_cpi_2026_07",
                event_type=EventType.US_CPI,
                scheduled_at="2026-07-14T12:30:00Z",
                consensus=0.3,
                actual=0.45,
            )
        ],
        news_items=[
            NewsItem(
                news_id="n1",
                title="Bitcoin falls after hot CPI",
                source="wire_reuters",
                published_at="2026-07-14T12:35:00Z",
                asset_tags=["BTC"],
            )
        ],
    )


def sentiment_text() -> str:
    return json.dumps(
        {"per_asset_sentiment": {s: -0.2 for s in SYMBOLS}, "global_sentiment": -0.25}
    )


def synthesis_text() -> str:
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


class SequencedFake:
    """A provider double that returns sentiment then synthesis text across successive calls.

    Re-seeds every two calls so the same instance can serve multiple runs (sentiment, synthesis,
    sentiment, synthesis, …).
    """

    def __init__(self, name: str = "openai") -> None:
        self._name = name
        self._i = 0

    @property
    def name(self) -> str:
        return self._name

    def complete(self, prompt: object, params: object) -> RawProviderResult:
        text = sentiment_text() if self._i % 2 == 0 else synthesis_text()
        self._i += 1
        return RawProviderResult(
            text=text, input_tokens=600, output_tokens=70, finish_reason="stop"
        )


def build_full_container() -> Container:
    """A container whose LLM succeeds (full, non-degraded run)."""
    return build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides={"openai": SequencedFake("openai")},
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )


def build_degraded_container() -> Container:
    """A container whose every provider fails (Degraded Run)."""
    from market_state_engine.reasoning.errors import ProviderCallError

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
