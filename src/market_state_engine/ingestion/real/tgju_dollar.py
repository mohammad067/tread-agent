"""Hybrid USD/IRR ingestion from Kifpool spot and TGJU daily history.

``HybridUsdIrrSource`` uses Kifpool's ``priceSellIRT`` as the current value and
timestamp while TGJU supplies the daily OHLC series. If Kifpool is unavailable,
``TgjuDollarSource`` provides the complete TGJU fallback and marks an aged quote
stale. A missing TGJU history never causes repeated synthetic candles: a live
Kifpool-only snapshot contains one honest observation plus a data-gap marker.

TGJU publishes its free-market dollar series in rial. Conversion to IRT (toman)
happens once at this ingestion boundary.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real.kifpool import KifpoolUsdIrrSource

_log = logging.getLogger("ingestion.real.tgju_dollar")

_LIVE_URL = "https://call4.tgju.org/ajax.json"
_HISTORY_URL = "https://api.tgju.org/v1/market/indicator/summary-table-data/price_dollar_rl"
_LIVE_KEYS = ("price_dollar_rl", "price_dollar_dt")
_TARGET_BARS = 130
_RIALS_PER_TOMAN = 10.0
_DEFAULT_DEVIATION_THRESHOLD_PCT = 2.0
_DEFAULT_STALE_AFTER_MINUTES = 60
_TEHRAN_TIMEZONE = timezone(timedelta(hours=3, minutes=30))


class _SpotSource(Protocol):
    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot: ...


class _TgjuClient(Protocol):
    def fetch_live(self) -> dict[str, Any]: ...

    def fetch_history(self) -> list[object]: ...


class TgjuDollarClient:
    """HTTP client for TGJU's live free-dollar quote and daily history."""

    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch_live(self) -> dict[str, Any]:
        document = self._get_json(_LIVE_URL)
        current = document.get("current") if isinstance(document, dict) else None
        if not isinstance(current, dict):
            raise RuntimeError("TGJU dollar: live response has no current object")
        for key in _LIVE_KEYS:
            row = current.get(key)
            if isinstance(row, dict):
                return row
        raise RuntimeError("TGJU dollar: no price_dollar_rl or price_dollar_dt quote")

    def fetch_history(self) -> list[object]:
        document = self._get_json(_HISTORY_URL)
        rows = document.get("data") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("TGJU dollar: history response has no data array")
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
            raise RuntimeError(f"TGJU dollar HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"TGJU dollar network error: {exc}") from exc


class HybridUsdIrrSource:
    """Kifpool live spot plus TGJU daily history for ``USD_IRR`` only."""

    def __init__(
        self,
        spot_source: _SpotSource | None = None,
        tgju_client: _TgjuClient | None = None,
        *,
        deviation_threshold_pct: float = _DEFAULT_DEVIATION_THRESHOLD_PCT,
        stale_after_minutes: int = _DEFAULT_STALE_AFTER_MINUTES,
    ) -> None:
        if deviation_threshold_pct < 0:
            raise ValueError("deviation_threshold_pct must be non-negative")
        if stale_after_minutes < 0:
            raise ValueError("stale_after_minutes must be non-negative")
        self._spot = spot_source or KifpoolUsdIrrSource()
        self._tgju = tgju_client or TgjuDollarClient()
        self._deviation_threshold_pct = deviation_threshold_pct
        self._stale_after_minutes = stale_after_minutes

    def supports(self, symbol: str) -> bool:
        return symbol.upper() == "USD_IRR"

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if not self.supports(symbol):
            raise KeyError(f"hybrid USD/IRR supports only USD_IRR, got {symbol!r}")

        try:
            spot = self._spot.fetch_series("USD_IRR", ctx)
        except Exception as exc:
            _log.warning("kifpool_usd_irr_failed fallback=tgju err=%s", exc)
            return TgjuDollarSource(
                self._tgju, stale_after_minutes=self._stale_after_minutes
            ).fetch_series("USD_IRR", ctx)

        try:
            bars = _history_bars(self._tgju.fetch_history())
        except Exception as exc:
            _log.warning("tgju_dollar_history_failed fallback=kifpool_only err=%s", exc)
            return _kifpool_only_snapshot(spot, reason="tgju_history_unavailable")

        value = _snapshot_value(spot)
        reference_close = bars[-1][1]
        deviation_flags = _deviation_flags(
            value,
            reference_close,
            threshold_pct=self._deviation_threshold_pct,
        )
        payload = _hybrid_payload(spot, bars, value)
        _log.info(
            "hybrid_usd_irr_ok price_irt=%s as_of=%s bars=%s deviation_pct=%s",
            value,
            spot.as_of,
            len(bars),
            _deviation_pct(value, reference_close),
        )
        return RawSnapshot(
            source_id="kifpool_tgju",
            symbol="USD_IRR",
            payload=payload,
            as_of=spot.as_of,
            is_stale=spot.is_stale,
            stale_reason=spot.stale_reason,
            deviation_flags=deviation_flags,
            content_hash=content_hash(payload),
        )


class TgjuDollarSource:
    """Complete TGJU fallback for ``USD_IRR`` with age-based staleness."""

    def __init__(
        self,
        client: _TgjuClient | None = None,
        *,
        stale_after_minutes: int = _DEFAULT_STALE_AFTER_MINUTES,
    ) -> None:
        if stale_after_minutes < 0:
            raise ValueError("stale_after_minutes must be non-negative")
        self._client = client or TgjuDollarClient()
        self._stale_after_minutes = stale_after_minutes

    def supports(self, symbol: str) -> bool:
        return symbol.upper() == "USD_IRR"

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        return self.fetch_series(symbol, ctx)

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if not self.supports(symbol):
            raise KeyError(f"TGJU dollar supports only USD_IRR, got {symbol!r}")

        live = self._client.fetch_live()
        bars = _history_bars(self._client.fetch_history())
        payload = _tgju_payload(live, bars)
        as_of = str(payload["as_of"])
        age_minutes = _age_minutes(as_of, ctx.now)
        is_stale = age_minutes > self._stale_after_minutes
        stale_reason = f"tgju_quote_age_minutes={round(age_minutes)}" if is_stale else None
        _log.info(
            "tgju_dollar_ok price_irt=%s as_of=%s bars=%s stale=%s",
            payload["value"],
            as_of,
            len(bars),
            is_stale,
        )
        return RawSnapshot(
            source_id="tgju",
            symbol="USD_IRR",
            payload=payload,
            as_of=as_of,
            is_stale=is_stale,
            stale_reason=stale_reason,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )


def _hybrid_payload(
    spot: RawSnapshot,
    bars: list[tuple[str, float, float, float]],
    value: float,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "as_of": spot.as_of,
        "value": value,
        "closes": [bar[1] for bar in bars],
        "highs": [bar[2] for bar in bars],
        "lows": [bar[3] for bar in bars],
        "volumes": [0.0] * len(bars),
        "currency": "IRT",
        "daily_dates": [bar[0] for bar in bars],
    }
    for key in ("price_buy_irt", "price_change_percent"):
        if key in spot.payload:
            payload[key] = spot.payload[key]
    return payload


def _kifpool_only_snapshot(spot: RawSnapshot, *, reason: str) -> RawSnapshot:
    value = _snapshot_value(spot)
    payload: dict[str, object] = {
        "as_of": spot.as_of,
        "value": value,
        "closes": [value],
        "highs": [value],
        "lows": [value],
        "volumes": [0.0],
        "currency": "IRT",
        "daily_dates": [],
        "data_gaps": [reason],
    }
    return RawSnapshot(
        source_id="kifpool",
        symbol="USD_IRR",
        payload=payload,
        as_of=spot.as_of,
        is_stale=spot.is_stale,
        stale_reason=spot.stale_reason,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _tgju_payload(
    live: dict[str, Any], bars: list[tuple[str, float, float, float]]
) -> dict[str, object]:
    current = _price(live.get("p")) / _RIALS_PER_TOMAN
    current_high = _price(live.get("h", live.get("p"))) / _RIALS_PER_TOMAN
    current_low = _price(live.get("l", live.get("p"))) / _RIALS_PER_TOMAN
    live_timestamp = live.get("ts")
    as_of = _as_of(live_timestamp)
    live_date = _local_datetime(live_timestamp).date().isoformat()
    if live_date >= bars[-1][0]:
        merged = _merge_current(bars, current, current_high, current_low, live_date)
    else:
        merged = list(bars)
        _log.warning(
            "tgju_dollar_live_behind_history live_date=%s history_date=%s",
            live_date,
            bars[-1][0],
        )
    return {
        "as_of": as_of,
        "value": current,
        "closes": [bar[1] for bar in merged],
        "highs": [bar[2] for bar in merged],
        "lows": [bar[3] for bar in merged],
        "volumes": [0.0] * len(merged),
        "currency": "IRT",
        "daily_dates": [bar[0] for bar in merged],
    }


def _history_bars(rows: list[object]) -> list[tuple[str, float, float, float]]:
    parsed: list[tuple[str, float, float, float]] = []
    for raw in rows:
        row = raw.get("value") if isinstance(raw, dict) else raw
        if not isinstance(row, list) or len(row) < 7:
            continue
        try:
            low = _price(row[1]) / _RIALS_PER_TOMAN
            high = _price(row[2]) / _RIALS_PER_TOMAN
            close = _price(row[3]) / _RIALS_PER_TOMAN
            day = str(row[6]).replace("/", "-")
        except (TypeError, ValueError):
            continue
        parsed.append((day, close, high, low))
    if len(parsed) < _TARGET_BARS:
        raise RuntimeError(
            f"TGJU dollar: need at least {_TARGET_BARS} valid history rows, got {len(parsed)}"
        )
    return list(reversed(parsed[:_TARGET_BARS]))


def _merge_current(
    bars: list[tuple[str, float, float, float]],
    current: float,
    current_high: float,
    current_low: float,
    current_date: str,
) -> list[tuple[str, float, float, float]]:
    merged = list(bars)
    if merged[-1][0] == current_date:
        merged[-1] = (current_date, current, current_high, current_low)
    else:
        merged = [*merged, (current_date, current, current_high, current_low)][-_TARGET_BARS:]
    return merged


def _deviation_flags(
    live_value: float, reference_value: float, *, threshold_pct: float
) -> list[dict[str, object]]:
    deviation = _deviation_pct(live_value, reference_value)
    if deviation <= threshold_pct:
        return []
    return [
        {
            "code": "cross_source_price_deviation",
            "live_source": "kifpool",
            "reference_source": "tgju",
            "live_value_irt": live_value,
            "reference_close_irt": reference_value,
            "deviation_pct": deviation,
            "threshold_pct": threshold_pct,
        }
    ]


def _deviation_pct(left: float, right: float) -> float:
    if right <= 0:
        raise ValueError("reference price must be positive")
    return round(abs(left - right) / right * 100.0, 6)


def _snapshot_value(snapshot: RawSnapshot) -> float:
    value = snapshot.payload.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError("Kifpool USD/IRR snapshot has no positive numeric value")
    return float(value)


def _price(value: object) -> float:
    number = float(str(value).replace(",", "").strip())
    if number <= 0:
        raise ValueError(f"invalid TGJU price {value!r}")
    return number


def _as_of(value: object) -> str:
    return _local_datetime(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("TGJU dollar: live quote has no timestamp")
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=_TEHRAN_TIMEZONE)
    except ValueError as exc:
        raise RuntimeError(f"TGJU dollar: invalid timestamp {value!r}") from exc


def _age_minutes(as_of: str, now: datetime) -> float:
    observed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return max(0.0, (reference.astimezone(timezone.utc) - observed).total_seconds() / 60.0)
