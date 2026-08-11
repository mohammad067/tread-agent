"""Kifpool USDT/IRT → RawSnapshot for USD_IRR (priceSellIRT, تومان)."""

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

_log = logging.getLogger("ingestion.real.kifpool")

_URL = "https://api.kifpool.app/api/spot/price?symbol=USDT&format=json"
_TARGET_BARS = 130


class KifpoolClient:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch_usdt(self) -> dict[str, Any]:
        req = urllib.request.Request(
            _URL,
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
            raise RuntimeError(f"Kifpool HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Kifpool network error: {exc}") from exc

        row = body.get("USDT") if isinstance(body, dict) else None
        if not isinstance(row, dict):
            raise RuntimeError("Kifpool: missing USDT object")
        return row


def _payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    price = float(row["priceSellIRT"])
    if price <= 0:
        raise RuntimeError(f"invalid priceSellIRT={row.get('priceSellIRT')!r}")
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    closes = [price] * _TARGET_BARS
    return {
        "as_of": as_of,
        "value": price,
        "closes": closes,
        "highs": [price * 1.001] * _TARGET_BARS,
        "lows": [price * 0.999] * _TARGET_BARS,
        "volumes": [0.0] * _TARGET_BARS,
        "currency": "IRT",
        "price_buy_irt": row.get("priceBuyIRT"),
        "price_change_percent": row.get("priceChangePercent"),
    }


class KifpoolUsdIrrSource:
    def __init__(self, client: KifpoolClient | None = None) -> None:
        self._client = client or KifpoolClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() == "USD_IRR"

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if symbol.upper() != "USD_IRR":
            raise KeyError(f"only USD_IRR, got {symbol!r}")
        payload = _payload_from_row(self._client.fetch_usdt())
        _log.info("kifpool_usd_irr_ok price_irt=%s", payload["value"])
        return RawSnapshot(
            source_id="kifpool",
            symbol="USD_IRR",
            payload=payload,
            as_of=str(payload["as_of"]),
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )