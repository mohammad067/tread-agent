"""IngestBundle: multi-source live ingest + persisted last-good fallback.

MSE_INGEST=real flow:
  1) BTC/ETH ← CoinGecko + Kifpool + Gate spot observations → aggregate
  2) GOLD ← CoinGecko pax-gold
  3) USD_IRR ← Kifpool live + TGJU daily history (IRT)
  4) dominance / mcap (global) ← CoinMarketCap keyless global metrics
  5) fear&greed ← Alternative.me
  6) news ← RssNewsSource
  7) WTI ← TGJU Brent (oil_brent + energy-brent-oil)
  8) TOTAL_MCAP ← CoinMarketCap keyless global metrics (real 24h only)
  9) CPI ← config/events/us_cpi_latest.yaml
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from market_state_engine.core.dtos import MacroEvent, RawSnapshot, TotalMcapSample
from market_state_engine.core.run_context import RunContext
from market_state_engine.pipeline.orchestrator import IngestBundle

from .aggregate import aggregate_snapshots
from .coingecko import CoinGeckoClient, CoinGeckoPriceSource
from .coinmarketcap import (
    CoinMarketCapGlobalSource,
    CoinMarketCapSnapshots,
    enrich_total_mcap_history,
)
from .cpi_event import load_us_cpi_event
from .fear_greed import FearGreedSource
from .gate import GateCryptoPriceSource
from .kifpool_crypto import KifpoolCryptoPriceSource
from .news_feeds import RssNewsSource
from .tgju_dollar import HybridUsdIrrSource
from .tgju_oil import TgjuOilSource

_log = logging.getLogger("ingestion.real")

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

_CRYPTO_SYMBOLS = ("BTC", "ETH")
_ALL_SYMBOLS = ("BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP")
_FEAR_GREED_LAST_GOOD_KEY = "FEAR_GREED"


class TotalMcapHistoryStore(Protocol):
    def record_and_list(
        self, sample: TotalMcapSample, *, limit: int = 130
    ) -> list[TotalMcapSample]: ...


class LastGoodSnapshotStore(Protocol):
    def record(self, snapshot: RawSnapshot) -> None: ...

    def get(self, symbol: str) -> RawSnapshot | None: ...


def build_real_ingest_provider(
    history_store: TotalMcapHistoryStore,
    last_good_store: LastGoodSnapshotStore,
) -> Callable[[RunContext], IngestBundle]:
    def _ingest(ctx: RunContext) -> IngestBundle:
        return real_ingest_provider(
            ctx,
            history_store=history_store,
            last_good_store=last_good_store,
        )

    return _ingest


def real_ingest_provider(
    ctx: RunContext,
    *,
    history_store: TotalMcapHistoryStore | None = None,
    last_good_store: LastGoodSnapshotStore | None = None,
) -> IngestBundle:
    client = CoinGeckoClient()
    cg_price = CoinGeckoPriceSource(client)
    coinmarketcap = CoinMarketCapGlobalSource()
    kp_crypto = KifpoolCryptoPriceSource()
    gate_crypto = GateCryptoPriceSource()
    usd_src = HybridUsdIrrSource()
    wti_src = TgjuOilSource()
    fng = FearGreedSource()
    news_src = RssNewsSource()

    coinmarketcap_snapshots: CoinMarketCapSnapshots | None = None
    try:
        coinmarketcap_snapshots = coinmarketcap.fetch_all(ctx)
    except Exception as exc:
        _log.warning("real_coinmarketcap_unavailable err=%s", exc)
    if coinmarketcap_snapshots is not None and history_store is not None:
        try:
            live = coinmarketcap_snapshots.total_mcap
            value = live.payload.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError("CoinMarketCap TOTAL_MCAP value is invalid")
            sample = TotalMcapSample(
                symbol="TOTAL_MCAP",
                value=float(value),
                as_of=live.as_of,
                run_id=ctx.run_id,
            )
            history = history_store.record_and_list(sample, limit=130)
            coinmarketcap_snapshots = CoinMarketCapSnapshots(
                dominance=coinmarketcap_snapshots.dominance,
                global_mcap=coinmarketcap_snapshots.global_mcap,
                total_mcap=enrich_total_mcap_history(live, history),
            )
        except Exception as exc:
            _log.warning("real_total_mcap_history_unavailable err=%s", exc)

    indicator_snapshots: dict[str, RawSnapshot] = {}
    price_snapshots: dict[str, RawSnapshot] = {}

    for sym in _ALL_SYMBOLS:
        # --- BTC / ETH ---
        if sym in _CRYPTO_SYMBOLS:
            snaps: list[RawSnapshot] = []
            if cg_price.supports(sym):
                try:
                    snaps.append(cg_price.fetch_series(sym, ctx))
                    _log.info("crypto_src_ok symbol=%s source=coingecko", sym)
                except Exception as exc:
                    _log.warning("crypto_src_fail symbol=%s source=coingecko err=%s", sym, exc)
            if kp_crypto.supports(sym):
                try:
                    snaps.append(kp_crypto.fetch_series(sym, ctx))
                    _log.info("crypto_src_ok symbol=%s source=kifpool", sym)
                except Exception as exc:
                    _log.warning("crypto_src_fail symbol=%s source=kifpool err=%s", sym, exc)
            if gate_crypto.supports(sym):
                try:
                    snaps.append(gate_crypto.fetch_series(sym, ctx))
                    _log.info("crypto_src_ok symbol=%s source=gate", sym)
                except Exception as exc:
                    _log.warning("crypto_src_fail symbol=%s source=gate err=%s", sym, exc)

            if snaps:
                merged = aggregate_snapshots(
                    snaps,
                    prefer_source_id="coingecko",
                    max_deviation_pct=2.0,
                )
                if merged is not None:
                    _record_last_good(last_good_store, merged)
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
            last_good = _load_last_good(last_good_store, sym)
            if last_good is not None:
                indicator_snapshots[sym] = last_good
                price_snapshots[sym] = last_good
                continue
            _log.warning("real_price_unavailable symbol=%s (no live or last-good source)", sym)
            continue

        # --- GOLD ---
        if sym == "GOLD":
            if cg_price.supports(sym):
                try:
                    live = cg_price.fetch_series(sym, ctx)
                    merged = aggregate_snapshots([live], prefer_source_id="coingecko")
                    if merged is not None:
                        _record_last_good(last_good_store, merged)
                        indicator_snapshots[sym] = merged
                        price_snapshots[sym] = merged
                        _log.info("real_price_ok symbol=%s source=%s", sym, merged.source_id)
                        continue
                except Exception as exc:
                    _log.warning("real_gold_unavailable err=%s", exc)
            last_good = _load_last_good(last_good_store, sym)
            if last_good is not None:
                indicator_snapshots[sym] = last_good
                price_snapshots[sym] = last_good
                continue
            _log.warning("real_price_unavailable symbol=GOLD")
            continue

        # --- WTI (Brent via TGJU) ---
        if sym == "WTI":
            if wti_src.supports(sym):
                try:
                    live = wti_src.fetch_series(sym, ctx)
                    merged = aggregate_snapshots([live], prefer_source_id="tgju")
                    if merged is not None:
                        _record_last_good(last_good_store, merged)
                        indicator_snapshots[sym] = merged
                        price_snapshots[sym] = merged
                        _log.info(
                            "real_price_ok symbol=%s source=%s stale=%s",
                            sym,
                            merged.source_id,
                            merged.is_stale,
                        )
                        continue
                except Exception as exc:
                    _log.warning("real_wti_unavailable err=%s", exc)
            last_good = _load_last_good(last_good_store, sym)
            if last_good is not None:
                indicator_snapshots[sym] = last_good
                price_snapshots[sym] = last_good
                continue
            _log.warning("real_price_unavailable symbol=WTI")
            continue

        # --- USD_IRR ---
        if sym == "USD_IRR":
            if usd_src.supports(sym):
                try:
                    live = usd_src.fetch_series(sym, ctx)
                    _record_last_good(last_good_store, live)
                    indicator_snapshots[sym] = live
                    price_snapshots[sym] = live
                    _log.info(
                        "real_price_ok symbol=%s source=%s stale=%s flags=%s",
                        sym,
                        live.source_id,
                        live.is_stale,
                        live.deviation_flags,
                    )
                    continue
                except Exception as exc:
                    _log.warning("real_usd_irr_unavailable err=%s", exc)
            last_good = _load_last_good(last_good_store, sym)
            if last_good is not None:
                indicator_snapshots[sym] = last_good
                price_snapshots[sym] = last_good
            else:
                _log.warning("real_price_unavailable symbol=USD_IRR")
            continue

        # --- TOTAL_MCAP ---
        if sym == "TOTAL_MCAP":
            if coinmarketcap_snapshots is not None:
                live = coinmarketcap_snapshots.total_mcap
                _record_last_good(last_good_store, live)
                indicator_snapshots[sym] = live
                price_snapshots[sym] = live
                _log.info(
                    "real_price_ok symbol=TOTAL_MCAP source=coinmarketcap value=%s",
                    live.payload.get("value"),
                )
            else:
                _log.warning("real_total_mcap_unavailable source=coinmarketcap")
                last_good = _load_last_good(last_good_store, sym)
                if last_good is not None:
                    indicator_snapshots[sym] = last_good
                    price_snapshots[sym] = last_good
            continue

    global_snapshots: dict[str, RawSnapshot] = {}
    try:
        live_fear_greed = fng.fetch(ctx)
        global_snapshots["fear_greed"] = live_fear_greed
        _record_last_good(
            last_good_store,
            live_fear_greed.model_copy(update={"symbol": _FEAR_GREED_LAST_GOOD_KEY}),
        )
        _log.info("real_fear_greed_ok")
    except Exception as exc:
        _log.warning("real_fear_greed_unavailable err=%s", exc)
        last_good_fear_greed = _load_last_good(last_good_store, _FEAR_GREED_LAST_GOOD_KEY)
        if last_good_fear_greed is not None:
            global_snapshots["fear_greed"] = last_good_fear_greed.model_copy(
                update={"symbol": None}
            )

    if coinmarketcap_snapshots is not None:
        global_snapshots["dominance"] = coinmarketcap_snapshots.dominance
        global_snapshots["total_mcap"] = coinmarketcap_snapshots.global_mcap
    else:
        _log.warning("real_global_unavailable source=coinmarketcap")

    try:
        news_items = news_src.fetch_items(ctx)
        _log.info("real_news_ok count=%s", len(news_items))
    except Exception as exc:
        _log.warning("news_fallback_empty err=%s", exc)
        news_items = []

    events: list[MacroEvent] = []
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


def _record_last_good(store: LastGoodSnapshotStore | None, snapshot: RawSnapshot) -> None:
    if store is None:
        return
    try:
        store.record(snapshot)
    except Exception as exc:
        _log.warning(
            "last_good_store_failed symbol=%s source=%s err=%s",
            snapshot.symbol,
            snapshot.source_id,
            exc,
        )


def _load_last_good(store: LastGoodSnapshotStore | None, symbol: str) -> RawSnapshot | None:
    if store is None:
        return None
    try:
        snapshot = store.get(symbol)
    except Exception as exc:
        _log.warning("last_good_load_failed symbol=%s err=%s", symbol, exc)
        return None
    if snapshot is not None:
        _log.warning("last_good_used symbol=%s source=%s", symbol, snapshot.source_id)
    return snapshot
