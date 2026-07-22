"""Default ingestion provider for the composition root (dev/CI wiring).

Supplies the pipeline's per-run raw inputs. The dev environment is ``ingestion.mode: mock`` (see
``config/environments/dev.yaml``), so this uses the deterministic offline mock sources — no network.
Real source adapters (kifpool, crypto venues, feeds) are a later concern; this is the wiring seam
the composition root injects, not new business logic. FeatureEngine and scoring are unchanged.
"""

from __future__ import annotations

import math

from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import EventType
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.mocks.mock_sources import (
    MockDominanceSource,
    MockFearGreedSource,
    MockIndicatorInputSource,
    MockPriceSource,
    MockTotalMcapSource,
)
from market_state_engine.pipeline.orchestrator import IngestBundle

_SYMBOLS = ("BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP")
_AS_OF = "2026-07-14T12:45:00Z"


def _series(base: float, n: int = 130) -> dict[str, object]:
    closes = [base - 0.5 * i + 2.0 * math.sin(i / 3.0) for i in range(n)]
    return {
        "as_of": _AS_OF,
        "value": closes[-1],
        "closes": closes,
        "highs": [c + 3.0 for c in closes],
        "lows": [c - 3.0 for c in closes],
        "volumes": [1000.0 + 40.0 * i for i in range(n)],
    }


def mock_ingest_provider(ctx: RunContext) -> IngestBundle:
    """Fetch a deterministic ``IngestBundle`` for one run from the offline mock sources."""
    series = {s: _series(120.0 + i * 10) for i, s in enumerate(_SYMBOLS)}
    ind = MockIndicatorInputSource(series)
    price = MockPriceSource(series)
    return IngestBundle(
        indicator_snapshots={s: ind.fetch_series(s, ctx) for s in _SYMBOLS},
        price_snapshots={s: price.fetch(s, ctx) for s in _SYMBOLS},
        global_snapshots={
            "fear_greed": MockFearGreedSource(24, _AS_OF).fetch(ctx),
            "dominance": MockDominanceSource(56.8, _AS_OF).fetch(ctx),
            "total_mcap": MockTotalMcapSource(3.91e12, _AS_OF).fetch(ctx),
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
    )
