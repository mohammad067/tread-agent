"""CoinPaprika free global-market adapter.

Uses only ``GET /v1/global`` and normalizes the response into ``RawSnapshot`` records.
TOTAL_MCAP free feed is 24h-class; 6h/7d/30d are explicit gaps per contract until a
real series exists.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_DEFAULT_URL = "https://api.coinpaprika.com/v1/global"
_STALE_AFTER_SECONDS = 15 * 60


class CoinPaprikaClient:
    """Small urllib client kept inside the ingestion adapter boundary."""

    def __init__(self, url: str = _DEFAULT_URL, timeout_s: float = 30.0) -> None:
        self._url = url
        self._timeout_s = timeout_s

    def get_global(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url,
            headers={"Accept": "application/json", "User-Agent": "mse/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                decoded: object = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"CoinPaprika HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CoinPaprika network error: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("CoinPaprika global response is not an object")
        return decoded


class _GlobalClient(Protocol):
    def get_global(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CoinPaprikaSnapshots:
    dominance: RawSnapshot
    global_mcap: RawSnapshot
    total_mcap: RawSnapshot


class CoinPaprikaGlobalSource:
    """Build consistent dominance and market-cap snapshots from one global response."""

    def __init__(self, client: _GlobalClient | None = None) -> None:
        self._client = client or CoinPaprikaClient()

    def fetch_all(self, ctx: RunContext) -> CoinPaprikaSnapshots:
        data = self._client.get_global()
        market_cap = _positive_float(data.get("market_cap_usd"), "market_cap_usd")
        dominance = _bounded_float(
            data.get("bitcoin_dominance_percentage"),
            "bitcoin_dominance_percentage",
            minimum=0.0,
            maximum=100.0,
        )
        change_24h = _float(data.get("market_cap_change_24h"), "market_cap_change_24h")
        last_updated = _positive_float(data.get("last_updated"), "last_updated")
        as_of_dt = datetime.fromtimestamp(last_updated, tz=timezone.utc)
        as_of = as_of_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        age_seconds = (ctx.now.astimezone(timezone.utc) - as_of_dt).total_seconds()
        is_stale = age_seconds > _STALE_AFTER_SECONDS
        stale_reason = "coinpaprika_global_stale" if is_stale else None

        dominance_payload: dict[str, object] = {
            "as_of": as_of,
            "btc_dominance": dominance,
        }
        global_mcap_payload: dict[str, object] = {
            "as_of": as_of,
            "total_market_cap_usd": market_cap,
            "market_cap_change_24h": change_24h,
        }
        previous_cap = _previous_value(market_cap, change_24h)
        total_mcap_payload: dict[str, object] = {
            "as_of": as_of,
            "value": market_cap,
            "closes": [previous_cap, market_cap],
            "highs": [],
            "lows": [],
            "volumes": [],
            "currency": "USD",
            "history_limited": True,
            "horizon_changes": {
                "6h": None,
                "24h": change_24h,
                "7d": None,
                "30d": None,
            },
            "data_gaps": [
                "missing_6h_change",
                "missing_7d_change",
                "missing_30d_change",
            ],
        }
        return CoinPaprikaSnapshots(
            dominance=_snapshot(
                symbol=None,
                payload=dominance_payload,
                as_of=as_of,
                is_stale=is_stale,
                stale_reason=stale_reason,
            ),
            global_mcap=_snapshot(
                symbol=None,
                payload=global_mcap_payload,
                as_of=as_of,
                is_stale=is_stale,
                stale_reason=stale_reason,
            ),
            total_mcap=_snapshot(
                symbol="TOTAL_MCAP",
                payload=total_mcap_payload,
                as_of=as_of,
                is_stale=is_stale,
                stale_reason=stale_reason,
            ),
        )

    def fetch_dominance_and_mcap(self, ctx: RunContext) -> tuple[RawSnapshot, RawSnapshot]:
        snapshots = self.fetch_all(ctx)
        return snapshots.dominance, snapshots.global_mcap

    def fetch_total_mcap_series(self, ctx: RunContext) -> RawSnapshot:
        return self.fetch_all(ctx).total_mcap


def _snapshot(
    *,
    symbol: str | None,
    payload: dict[str, object],
    as_of: str,
    is_stale: bool,
    stale_reason: str | None,
) -> RawSnapshot:
    return RawSnapshot(
        source_id="coinpaprika",
        symbol=symbol,
        payload=payload,
        as_of=as_of,
        is_stale=is_stale,
        stale_reason=stale_reason,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"CoinPaprika global: {field} missing or invalid")
    return float(value)


def _positive_float(value: object, field: str) -> float:
    result = _float(value, field)
    if result <= 0:
        raise RuntimeError(f"CoinPaprika global: {field} must be positive")
    return result


def _bounded_float(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    result = _float(value, field)
    if not minimum <= result <= maximum:
        raise RuntimeError(f"CoinPaprika global: {field} out of range")
    return result


def _previous_value(current: float, change_pct: float) -> float:
    denominator = 1.0 + change_pct / 100.0
    if denominator <= 0:
        raise RuntimeError("CoinPaprika global: market_cap_change_24h is invalid")
    return current / denominator
