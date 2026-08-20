"""Keyless Gate spot-candle adapter for BTC and ETH.

Gate exposes direct exchange observations in USDT pairs. The adapter keeps that
source-quote fact in the replay payload while normalizing the contract currency
to USD-equivalent for cross-source comparison. It supports only BTC and ETH.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_log = logging.getLogger("ingestion.real.gate")

_DEFAULT_BASE = "https://api.gateio.ws/api/v4"
_SYMBOL_PAIRS = {"BTC": "BTC_USDT", "ETH": "ETH_USDT"}
_SOURCE_INTERVAL = "1h"
_SOURCE_LIMIT = 800
_SIX_HOURS_SECONDS = 6 * 60 * 60
_TARGET_BARS = 130


class GateClient:
    """Small urllib client for Gate's unauthenticated spot-candlestick API."""

    def __init__(self, base_url: str = _DEFAULT_BASE, timeout_s: float = 20.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def fetch_candles(self, currency_pair: str, *, limit: int) -> list[list[object]]:
        query = urllib.parse.urlencode(
            {
                "currency_pair": currency_pair,
                "interval": _SOURCE_INTERVAL,
                "limit": str(limit),
            }
        )
        url = f"{self._base}/spot/candlesticks?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "mse/0.1 (market-state-engine)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body: object = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Gate HTTP {exc.code} for {currency_pair}: {raw}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Gate network error for {currency_pair}: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gate invalid JSON for {currency_pair}") from exc

        if not isinstance(body, list) or not body:
            raise RuntimeError(f"Gate returned no candles for {currency_pair}")
        rows: list[list[object]] = []
        for row in body:
            if not isinstance(row, list):
                raise RuntimeError(f"Gate returned an invalid candle for {currency_pair}")
            rows.append(row)
        return rows


class GateCryptoPriceSource:
    """Normalize Gate BTC_USDT/ETH_USDT hourly candles into 130 six-hour bars."""

    def __init__(self, client: GateClient | None = None) -> None:
        self._client = client or GateClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in _SYMBOL_PAIRS

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        sym = symbol.upper()
        currency_pair = _SYMBOL_PAIRS.get(sym)
        if currency_pair is None:
            raise KeyError(f"Gate crypto supports only BTC/ETH, got {symbol!r}")

        source_rows = self._client.fetch_candles(currency_pair, limit=_SOURCE_LIMIT)
        bars = _six_hour_bars(source_rows, currency_pair)
        as_of = ctx.now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        source_as_of = datetime.fromtimestamp(bars[-1][0], tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload: dict[str, Any] = {
            "as_of": as_of,
            "value": bars[-1][1],
            "closes": [bar[1] for bar in bars],
            "highs": [bar[2] for bar in bars],
            "lows": [bar[3] for bar in bars],
            "volumes": [bar[4] for bar in bars],
            "currency": "USD",
            "source_pair": currency_pair,
            "source_quote_currency": "USDT",
            "source_as_of": source_as_of,
            "quote_normalization": "USDT_USD_NOMINAL",
        }
        _log.info(
            "gate_crypto_ok symbol=%s pair=%s price_usdt=%s bars=%s",
            sym,
            currency_pair,
            payload["value"],
            len(bars),
        )
        return RawSnapshot(
            source_id="gate",
            symbol=sym,
            payload=payload,
            as_of=as_of,
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )


def _six_hour_bars(
    rows: list[list[object]], currency_pair: str
) -> list[tuple[int, float, float, float, float]]:
    hourly = sorted((_parse_candle(row, currency_pair) for row in rows), key=lambda row: row[0])
    buckets: dict[int, list[tuple[int, float, float, float, float, float]]] = {}
    for candle in hourly:
        bucket = candle[0] // _SIX_HOURS_SECONDS * _SIX_HOURS_SECONDS
        buckets.setdefault(bucket, []).append(candle)

    aggregated: list[tuple[int, float, float, float, float]] = []
    for timestamp in sorted(buckets):
        candles = buckets[timestamp]
        aggregated.append(
            (
                timestamp,
                candles[-1][1],
                max(candle[2] for candle in candles),
                min(candle[3] for candle in candles),
                sum(candle[5] for candle in candles),
            )
        )
    if len(aggregated) < _TARGET_BARS:
        raise RuntimeError(
            f"Gate returned only {len(aggregated)} six-hour bars for {currency_pair}; "
            f"need {_TARGET_BARS}"
        )
    return aggregated[-_TARGET_BARS:]


def _parse_candle(
    row: list[object], currency_pair: str
) -> tuple[int, float, float, float, float, float]:
    # Gate v4: timestamp, quote volume, close, high, low, open, base volume, closed.
    if len(row) < 7:
        raise RuntimeError(f"Gate returned a short candle for {currency_pair}")
    try:
        timestamp = int(str(row[0]))
        close = float(str(row[2]))
        high = float(str(row[3]))
        low = float(str(row[4]))
        open_price = float(str(row[5]))
        volume = float(str(row[6]))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Gate returned a non-numeric candle for {currency_pair}") from exc
    if timestamp <= 0 or min(close, high, low, open_price) <= 0 or volume < 0:
        raise RuntimeError(f"Gate returned an invalid candle value for {currency_pair}")
    return timestamp, close, high, low, open_price, volume
