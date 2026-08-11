"""CoinGecko HTTP adapters → RawSnapshot (no vendor types leak past this module).

Public endpoints used (no API key required for modest rate limits):
  - GET /api/v3/coins/{id}/market_chart
  - GET /api/v3/global

  روند: HTTP به CoinGecko → JSON → payload با closes/highs/lows/volumes/value
     → RawSnapshot(source_id="coingecko") برای هسته.
"""


from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "GOLD": "pax-gold",  # پروکسی اونس به USD؛ جایگزین: "tether-gold"
}

_DEFAULT_BASE = "https://api.coingecko.com/api/v3"
_CHART_DAYS = 30
_TARGET_BARS = 130


class CoinGeckoClient:
    def __init__(self, base_url: str = _DEFAULT_BASE, timeout_s: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self._base}{path}{query}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "mse/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"CoinGecko HTTP {exc.code} for {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CoinGecko network error for {path}: {exc}") from exc


def _iso_z(ms: float | int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _downsample(values: list[float], n: int) -> list[float]:
    if len(values) <= n:
        return values
    if n <= 1:
        return [values[-1]]
    step = (len(values) - 1) / (n - 1)
    return [values[int(round(i * step))] for i in range(n)]


def _chart_to_ohlcv(prices: list[list[float]], volumes: list[list[float]]) -> dict[str, Any]:
    closes = [float(p[1]) for p in prices if len(p) >= 2]
    vol_by_ts = {int(v[0]): float(v[1]) for v in volumes if len(v) >= 2}
    volumes_aligned = [vol_by_ts.get(int(p[0]), 0.0) for p in prices if len(p) >= 2]

    closes = _downsample(closes, _TARGET_BARS)
    volumes_aligned = _downsample(volumes_aligned, _TARGET_BARS)

    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    last_ts = prices[-1][0] if prices else 0
    as_of = (
        _iso_z(last_ts)
        if last_ts
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    value = closes[-1] if closes else 0.0
    return {
        "as_of": as_of,
        "value": value,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes_aligned,
    }


class CoinGeckoPriceSource:
    def __init__(self, client: CoinGeckoClient | None = None) -> None:
        self._client = client or CoinGeckoClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in _COINGECKO_IDS

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self._fetch(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self._fetch(symbol, ctx)

    def _fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        sym = symbol.upper()
        coin_id = _COINGECKO_IDS.get(sym)
        if coin_id is None:
            raise KeyError(f"CoinGecko has no mapping for symbol {symbol!r}")

        data = self._client.get_json(
            f"/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": str(_CHART_DAYS)},
        )
        prices = data.get("prices") or []
        volumes = data.get("total_volumes") or []
        if not prices:
            raise RuntimeError(f"CoinGecko returned empty prices for {coin_id}")

        payload = _chart_to_ohlcv(prices, volumes)
        return RawSnapshot(
            source_id="coingecko",
            symbol=sym,
            payload=payload,
            as_of=str(payload["as_of"]),
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )


class CoinGeckoGlobalSource:
    def __init__(self, client: CoinGeckoClient | None = None) -> None:
        self._client = client or CoinGeckoClient()

    def fetch_dominance_and_mcap(self, ctx: RunContext) -> tuple[RawSnapshot, RawSnapshot]:
        data = self._client.get_json("/global")
        g = data.get("data") or data
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pct = g.get("market_cap_percentage") or {}
        btc_dom = float(pct.get("btc") or g.get("btc_dominance") or 0.0)
        total = g.get("total_market_cap") or {}
        total_usd = float(total.get("usd") or 0.0)

        dom_payload = {"btc_dominance": btc_dom, "as_of": as_of}
        mcap_payload = {"total_market_cap_usd": total_usd, "as_of": as_of}

        dom = RawSnapshot(
            source_id="coingecko",
            symbol=None,
            payload=dom_payload,
            as_of=as_of,
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(dom_payload),
        )
        mcap = RawSnapshot(
            source_id="coingecko",
            symbol=None,
            payload=mcap_payload,
            as_of=as_of,
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(mcap_payload),
        )
        return dom, mcap