"""TGJU Brent crude adapter (engine symbol: WTI).

Live:  call4.tgju.org/ajax.json → current.oil_brent  (intraday ts)
History: api.tgju.org/.../summary-table-data/energy-brent-oil  (daily OHLC)

Daily series only — 6h is approximate. Engine asset id stays WTI.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_log = logging.getLogger("ingestion.real.tgju_oil")

_LIVE_URL = "https://call4.tgju.org/ajax.json"
_LIVE_KEY = "oil_brent"
_HISTORY_URL = (
    "https://api.tgju.org/v1/market/indicator/summary-table-data/energy-brent-oil"
)
_TARGET_BARS = 130
_STALE_AFTER_DAYS = 2
_TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


class TgjuOilClient:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch_live(self) -> dict[str, Any]:
        document = self._get_json(_LIVE_URL)
        current = document.get("current") if isinstance(document, dict) else None
        row = current.get(_LIVE_KEY) if isinstance(current, dict) else None
        if not isinstance(row, dict) or row.get("p") is None:
            raise RuntimeError("TGJU oil: live response has no oil_brent quote")
        return row

    def fetch_history(self) -> list[object]:
        document = self._get_json(_HISTORY_URL)
        rows = document.get("data") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("TGJU oil: history response has no data array")
        return list(rows)

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "mse/0.1 (market-state-engine)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"TGJU oil HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"TGJU oil network error: {exc}") from exc


class TgjuOilSource:
    """Brent series from TGJU, exposed as engine symbol WTI."""

    def __init__(self, client: TgjuOilClient | None = None) -> None:
        self._client = client or TgjuOilClient()

    def supports(self, symbol: str) -> bool:
        return symbol.upper() == "WTI"

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if not self.supports(symbol):
            raise KeyError(f"TGJU oil supports only WTI, got {symbol!r}")

        live = self._client.fetch_live()
        history = self._client.fetch_history()
        payload, is_stale, stale_reason = _build_payload(live, history)
        closes = payload["closes"]
        _log.info(
            "tgju_oil_ok benchmark=brent price_usd=%s as_of=%s bars=%s stale=%s",
            payload["value"],
            payload["as_of"],
            len(closes) if isinstance(closes, list) else 0,
            is_stale,
        )
        return RawSnapshot(
            source_id="tgju",
            symbol="WTI",
            payload=payload,
            as_of=str(payload["as_of"]),
            is_stale=is_stale,
            stale_reason=stale_reason,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )


def _build_payload(
    live: dict[str, Any], history: list[object]
) -> tuple[dict[str, object], bool, str | None]:
    live_price = _price(live.get("p"))
    live_high = _price(live.get("h", live.get("p")))
    live_low = _price(live.get("l", live.get("p")))
    live_dt = _local_datetime(live.get("ts"))
    live_date = live_dt.date().isoformat()

    bars = _history_bars(history)
    hist_date, hist_close, hist_high, hist_low = bars[-1]

    if live_date >= hist_date:
        current, current_high, current_low = live_price, live_high, live_low
        as_of = live_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        merge_date = live_date
    else:
        current, current_high, current_low = hist_close, hist_high, hist_low
        as_of = f"{hist_date}T12:00:00Z"
        merge_date = hist_date
        _log.warning(
            "tgju_oil_live_behind_history live_date=%s hist_date=%s using_hist_close=%s",
            live_date,
            hist_date,
            hist_close,
        )

    closes, highs, lows, dates = _merge_live(
        bars, current, current_high, current_low, merge_date
    )

    today = datetime.now(_TEHRAN_TZ).date()
    age_days = (today - date.fromisoformat(merge_date)).days
    is_stale = age_days > _STALE_AFTER_DAYS
    stale_reason = f"brent_as_of_age_days={age_days}" if is_stale else None

    return (
        {
            "as_of": as_of,
            "value": current,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": [0.0] * len(closes),
            "currency": "USD",
            "daily_dates": dates,
            "benchmark": "brent",
        },
        is_stale,
        stale_reason,
    )


def _history_bars(rows: list[object]) -> list[tuple[str, float, float, float]]:
    parsed: list[tuple[str, float, float, float]] = []
    for raw in rows:
        row = raw.get("value") if isinstance(raw, dict) else raw
        if not isinstance(row, list) or len(row) < 7:
            continue
        try:
            low = _price(row[1])
            high = _price(row[2])
            close = _price(row[3])
            day = str(row[6]).replace("/", "-")
        except (TypeError, ValueError):
            continue
        parsed.append((day, close, high, low))
    if len(parsed) < _TARGET_BARS:
        raise RuntimeError(
            f"TGJU oil: need at least {_TARGET_BARS} valid history rows, got {len(parsed)}"
        )
    return list(reversed(parsed[:_TARGET_BARS]))


def _merge_live(
    bars: list[tuple[str, float, float, float]],
    current: float,
    current_high: float,
    current_low: float,
    merge_date: str,
) -> tuple[list[float], list[float], list[float], list[str]]:
    bars = list(bars)
    if bars[-1][0] == merge_date:
        bars[-1] = (merge_date, current, current_high, current_low)
    else:
        bars = [*bars, (merge_date, current, current_high, current_low)][-_TARGET_BARS:]
    return (
        [b[1] for b in bars],
        [b[2] for b in bars],
        [b[3] for b in bars],
        [b[0] for b in bars],
    )


def _price(value: object) -> float:
    number = float(str(value).replace(",", "").strip())
    if number <= 0:
        raise ValueError(f"invalid TGJU price {value!r}")
    return number


def _local_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("TGJU oil: live quote has no timestamp")
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=_TEHRAN_TZ)
    except ValueError as exc:
        raise RuntimeError(f"TGJU oil: invalid timestamp {value!r}") from exc