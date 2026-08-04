"""IngestBundle: live BTC/ETH + news feeds + fear&greed; other assets mock until adapters exist.

روند MSE_INGEST=real:
  1) قیمت BTC/ETH ← CoinGecko
  2) dominance / total mcap ← CoinGecko
  3) fear&greed ← Alternative.me
  4) news_items ← RssNewsSource (چند فید؛ تگ چندبازار)
  5) GOLD/WTI/USD_IRR + CPI event ← mock
  6) fail جزئی → fallback؛ run abort نمی‌شود
"""

from __future__ import annotations

import logging

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

from .aggregate import aggregate_snapshots
from .coingecko import CoinGeckoClient, CoinGeckoGlobalSource, CoinGeckoPriceSource
from .fear_greed import FearGreedSource
from .news_feeds import RssNewsSource

_log = logging.getLogger("ingestion.real")

_REAL_SYMBOLS = ("BTC", "ETH")
_ALL_SYMBOLS = ("BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP")
_AS_OF_FALLBACK = "2026-07-14T12:45:00Z"


def _mock_series_bundle() -> dict[str, dict]:
    import math

    out: dict[str, dict] = {}
    for i, s in enumerate(_ALL_SYMBOLS):
        base = 120.0 + i * 10
        n = 130
        closes = [base - 0.5 * j + 2.0 * math.sin(j / 3.0) for j in range(n)]
        out[s] = {
            "as_of": _AS_OF_FALLBACK,
            "value": closes[-1],
            "closes": closes,
            "highs": [c + 3.0 for c in closes],
            "lows": [c - 3.0 for c in closes],
            "volumes": [1000.0 + 40.0 * j for j in range(n)],
        }
    return out


def real_ingest_provider(ctx: RunContext) -> IngestBundle:
    client = CoinGeckoClient()
    cg_price = CoinGeckoPriceSource(client)
    cg_global = CoinGeckoGlobalSource(client)
    fng = FearGreedSource()
    news_src = RssNewsSource()

    mock_series = _mock_series_bundle()
    mock_ind = MockIndicatorInputSource(mock_series)
    mock_price = MockPriceSource(mock_series)

    indicator_snapshots: dict = {}
    price_snapshots: dict = {}

    for sym in _ALL_SYMBOLS:
        if sym in _REAL_SYMBOLS and cg_price.supports(sym):
            try:
                live = cg_price.fetch_series(sym, ctx)
                merged = aggregate_snapshots([live], prefer_source_id="coingecko")
                assert merged is not None
                indicator_snapshots[sym] = merged
                price_snapshots[sym] = merged
                _log.info("real_price_ok symbol=%s source=%s", sym, merged.source_id)
                continue
            except Exception as exc:  # noqa: BLE001
                _log.warning("real_price_fallback_mock symbol=%s err=%s", sym, exc)
        indicator_snapshots[sym] = mock_ind.fetch_series(sym, ctx)
        price_snapshots[sym] = mock_price.fetch(sym, ctx)

    global_snapshots: dict = {}
    try:
        global_snapshots["fear_greed"] = fng.fetch(ctx)
        _log.info("real_fear_greed_ok")
    except Exception as exc:  # noqa: BLE001
        _log.warning("fear_greed_fallback_mock err=%s", exc)
        global_snapshots["fear_greed"] = MockFearGreedSource(24, _AS_OF_FALLBACK).fetch(ctx)

    try:
        dom, mcap = cg_global.fetch_dominance_and_mcap(ctx)
        global_snapshots["dominance"] = dom
        global_snapshots["total_mcap"] = mcap
    except Exception as exc:  # noqa: BLE001
        _log.warning("real_global_fallback_mock err=%s", exc)
        global_snapshots["dominance"] = MockDominanceSource(56.8, _AS_OF_FALLBACK).fetch(ctx)
        global_snapshots["total_mcap"] = MockTotalMcapSource(3.91e12, _AS_OF_FALLBACK).fetch(ctx)

    try:
        news_items = news_src.fetch_items(ctx)
        _log.info("real_news_ok count=%s", len(news_items))
    except Exception as exc:  # noqa: BLE001
        _log.warning("news_fallback_empty err=%s", exc)
        news_items = []

    events = [
        MacroEvent(
            event_id="us_cpi_2026_07",
            event_type=EventType.US_CPI,
            scheduled_at="2026-07-14T12:30:00Z",
            consensus=0.3,
            actual=0.45,
        )
    ]

    return IngestBundle(
        indicator_snapshots=indicator_snapshots,
        price_snapshots=price_snapshots,
        global_snapshots=global_snapshots,
        events=events,
        news_items=news_items,
    )