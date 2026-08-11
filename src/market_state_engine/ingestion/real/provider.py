"""IngestBundle: multi-source live ingest + mock fallback.

روند MSE_INGEST=real:
  1) BTC/ETH ← CoinGecko + Kifpool (USD) → aggregate_snapshots
  2) GOLD ← CryptoBaz XAUUSD (USD)
  3) USD_IRR ← Kifpool priceSellIRT (IRT / USDT proxy)
  4) dominance / mcap ← CoinGecko
  5) fear&greed ← Alternative.me
  6) news ← RssNewsSource
  7) WTI / TOTAL_MCAP ← mock (موقت)
  8) CPI ← config/events/us_cpi_latest.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path

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
from .cpi_event import load_us_cpi_event
from .fear_greed import FearGreedSource
from .kifpool import KifpoolUsdIrrSource
from .kifpool_crypto import KifpoolCryptoPriceSource
from .news_feeds import RssNewsSource

_log = logging.getLogger("ingestion.real")

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

_CRYPTO_SYMBOLS = ("BTC", "ETH")
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
    kp_crypto = KifpoolCryptoPriceSource()
    usd_src = KifpoolUsdIrrSource()
    fng = FearGreedSource()
    news_src = RssNewsSource()

    mock_series = _mock_series_bundle()
    mock_ind = MockIndicatorInputSource(mock_series)
    mock_price = MockPriceSource(mock_series)

    indicator_snapshots: dict = {}
    price_snapshots: dict = {}

    for sym in _ALL_SYMBOLS:
        # --- BTC / ETH: CoinGecko (سری) + Kifpool (اسپات USD) ---
        if sym in _CRYPTO_SYMBOLS:
            snaps = []
            if cg_price.supports(sym):
                try:
                    snaps.append(cg_price.fetch_series(sym, ctx))
                    _log.info("crypto_src_ok symbol=%s source=coingecko", sym)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("crypto_src_fail symbol=%s source=coingecko err=%s", sym, exc)
            if kp_crypto.supports(sym):
                try:
                    snaps.append(kp_crypto.fetch_series(sym, ctx))
                    _log.info("crypto_src_ok symbol=%s source=kifpool", sym)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("crypto_src_fail symbol=%s source=kifpool err=%s", sym, exc)

            if snaps:
                # prefer coingecko: سری تاریخی برای RSI؛ انحراف با kifpool در deviation_flags
                merged = aggregate_snapshots(
                    snaps,
                    prefer_source_id="coingecko",
                    max_deviation_pct=2.0,
                )
                if merged is not None:
                    indicator_snapshots[sym] = merged
                    price_snapshots[sym] = merged
                    _log.info(
                        "real_price_ok symbol=%s source=%s n_sources=%s flags=%s",
                        sym,
                        merged.source_id,
                        len(snaps),
                        merged.deviation_flags,
                    )
                    continue
            _log.warning("real_price_fallback_mock symbol=%s (no live crypto source)", sym)

# --- GOLD ← CoinGecko pax-gold (USD + سری برای 6h/24h/30d) ---
        if sym == "GOLD" and cg_price.supports(sym):
            try:
                live = cg_price.fetch_series(sym, ctx)
                merged = aggregate_snapshots([live], prefer_source_id="coingecko")
                if merged is not None:
                    indicator_snapshots[sym] = merged
                    price_snapshots[sym] = merged
                    _log.info("real_price_ok symbol=%s source=%s", sym, merged.source_id)
                    continue
            except Exception as exc:  # noqa: BLE001
                _log.warning("real_gold_fallback_mock err=%s", exc)

        # --- USD_IRR ← Kifpool priceSellIRT (IRT) ---
        if sym == "USD_IRR" and usd_src.supports(sym):
            try:
                live = usd_src.fetch_series(sym, ctx)
                merged = aggregate_snapshots([live], prefer_source_id="kifpool")
                if merged is not None:
                    indicator_snapshots[sym] = merged
                    price_snapshots[sym] = merged
                    _log.info("real_price_ok symbol=%s source=%s", sym, merged.source_id)
                    continue
            except Exception as exc:  # noqa: BLE001
                _log.warning("real_usd_irr_fallback_mock err=%s", exc)

        # --- بقیه موقت mock ---
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

    events: list = []
    cpi = load_us_cpi_event(_PROJECT_ROOT)
    if cpi is not None:
        events.append(cpi)
        _log.info("cpi_event_ok event_id=%s", cpi.event_id)
    else:
        _log.warning("cpi_event_missing")

    return IngestBundle(
        indicator_snapshots=indicator_snapshots,
        price_snapshots=price_snapshots,
        global_snapshots=global_snapshots,
        events=events,
        news_items=news_items,
    )