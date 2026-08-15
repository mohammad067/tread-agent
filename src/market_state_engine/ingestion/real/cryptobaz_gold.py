"""CryptoBaz marketCommodityLive → RawSnapshot for GOLD (row abbr=XAUUSD).

GET https://api.cryptobaz.io/api/market-overview/marketCommodityLive
پاسخ: data[] شامل WTI، XAUUSD، فلزات، … → فقط XAUUSD برای GOLD.
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

_log = logging.getLogger("ingestion.real.cryptobaz_gold")

_URL = "https://api.cryptobaz.io/api/market-overview/marketCommodityLive"
_TARGET_BARS = 130


class CryptoBazClient:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch_rows(self) -> list[dict[str, Any]]:
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
            raise RuntimeError(f"CryptoBaz HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CryptoBaz network error: {exc}") from exc

        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("CryptoBaz: empty or invalid data[]")
        return rows


def _pick_xau(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        abbr = str(row.get("abbr") or "").upper().replace("/", "")
        if abbr in ("XAUUSD", "XAU"):
            return row
    raise RuntimeError(f"CryptoBaz: no XAUUSD row (abbrs={[r.get('abbr') for r in rows]})")


def _as_of(row: dict[str, Any]) -> str:
    raw = row.get("created_at")
    if isinstance(raw, str) and raw.strip():
        s = raw.strip().replace(" ", "T")
        if not s.endswith("Z") and "+" not in s:
            s += "Z"
        return s
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    price = float(row.get("close") or row.get("navClose") or 0)
    if price <= 0:
        raise RuntimeError(f"CryptoBaz XAUUSD invalid close: {row.get('close')!r}")

    # بدون تاریخچه در این API: سری تخت (قیمت زنده OK؛ RSI ضعیف)
    closes = [price] * _TARGET_BARS
    highs = [price * 1.002] * _TARGET_BARS
    lows = [price * 0.998] * _TARGET_BARS
    volumes = [0.0] * _TARGET_BARS

    return {
        "as_of": _as_of(row),
        "value": price,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "currency": "USD",
        "change_percent": row.get("changePercent"),
        "source_abbr": row.get("abbr"),
        "source_name": row.get("name"),
    }


class CryptoBazGoldSource:
    def __init__(self, client: CryptoBazClient | None = None) -> None:
        self._client = client or CryptoBazClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() == "GOLD"

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if symbol.upper() != "GOLD":
            raise KeyError(f"only GOLD supported, got {symbol!r}")
        row = _pick_xau(self._client.fetch_rows())
        payload = _payload_from_row(row)
        _log.info(
            "cryptobaz_gold_ok price=%s as_of=%s",
            payload["value"],
            payload["as_of"],
        )
        return RawSnapshot(
            source_id="cryptobaz",
            symbol="GOLD",
            payload=payload,
            as_of=str(payload["as_of"]),
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )
