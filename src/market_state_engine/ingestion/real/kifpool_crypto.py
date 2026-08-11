"""Kifpool spot USD → RawSnapshot for BTC / ETH.

GET https://api.kifpool.app/api/spot/price?symbol={BTC|ETH}&format=json
فیلد قیمت دلاری: price
(priceSellIRT برای USD_IRR است — اینجا استفاده نمی‌شود)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_log = logging.getLogger("ingestion.real.kifpool_crypto")

_BASE = "https://api.kifpool.app/api/spot/price"
_SYMBOLS = {"BTC": "BTC", "ETH": "ETH"}
_TARGET_BARS = 130


class KifpoolCryptoClient:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch_symbol(self, api_symbol: str) -> dict[str, Any]:
        url = f"{_BASE}?symbol={api_symbol}&format=json"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "mse/0.1 (market-state-engine)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Kifpool HTTP {exc.code} {api_symbol}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Kifpool network error: {exc}") from exc

        row = body.get(api_symbol) if isinstance(body, dict) else None
        if not isinstance(row, dict):
            raise RuntimeError(f"Kifpool: missing {api_symbol} in response")
        return row


def _payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    # قیمت دلاری صرافی/کیف‌پول
    price = float(row["price"])
    if price <= 0:
        raise RuntimeError(f"Kifpool invalid USD price={row.get('price')!r}")

    high = float(row.get("high") or price)
    low = float(row.get("low") or price)
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # بدون OHLCV تاریخی: سری نزدیک به اسپات (RSI ضعیف؛ قیمت زنده OK)
    closes = [price] * _TARGET_BARS
    highs = [max(price, high)] * _TARGET_BARS
    lows = [min(price, low)] * _TARGET_BARS
    volumes = [float(row.get("volume") or 0.0)] * _TARGET_BARS

    return {
        "as_of": as_of,
        "value": price,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "currency": "USD",
        "price_change_percent": row.get("priceChangePercent"),
    }


class KifpoolCryptoPriceSource:
    def __init__(self, client: KifpoolCryptoClient | None = None) -> None:
        self._client = client or KifpoolCryptoClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in _SYMBOLS

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        sym = symbol.upper()
        api_sym = _SYMBOLS.get(sym)
        if api_sym is None:
            raise KeyError(f"Kifpool crypto only BTC/ETH, got {symbol!r}")
        row = self._client.fetch_symbol(api_sym)
        payload = _payload_from_row(row)
        _log.info(
            "kifpool_crypto_ok symbol=%s price_usd=%s",
            sym,
            payload["value"],
        )
        return RawSnapshot(
            source_id="kifpool",
            symbol=sym,
            payload=payload,
            as_of=str(payload["as_of"]),
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )