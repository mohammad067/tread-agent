"""Keyless CoinMarketCap global metrics adapter.

Uses only ``GET /public-api/v1/global-metrics/quotes/latest``. The latest response
provides a real 24h market-cap change; 6h/7d/30d remain explicit gaps because this
adapter does not fabricate a historical series.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, cast

from market_state_engine.core.dtos import RawSnapshot, TotalMcapSample
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_DEFAULT_URL = (
    "https://pro-api.coinmarketcap.com/public-api/v1/global-metrics/quotes/latest"
)
_STALE_AFTER_SECONDS = 15 * 60
_HISTORY_LIMIT = 130
_HISTORY_TOLERANCE = timedelta(hours=12)


class CoinMarketCapClient:
    """Minimal urllib client for CoinMarketCap's keyless public endpoint."""

    def __init__(self, url: str = _DEFAULT_URL, timeout_s: float = 30.0) -> None:
        self._url = url
        self._timeout_s = timeout_s

    def get_latest(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self._url,
            headers={"Accept": "application/json", "User-Agent": "mse/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                decoded: object = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"CoinMarketCap HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CoinMarketCap network error: {exc}") from exc
        except TimeoutError as exc:
            raise RuntimeError("CoinMarketCap network timeout") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("CoinMarketCap returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("CoinMarketCap response is not an object")
        return cast(dict[str, Any], decoded)


class _LatestClient(Protocol):
    def get_latest(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CoinMarketCapSnapshots:
    dominance: RawSnapshot
    global_mcap: RawSnapshot
    total_mcap: RawSnapshot


class CoinMarketCapGlobalSource:
    """Build all global snapshots from one validated CoinMarketCap response."""

    def __init__(self, client: _LatestClient | None = None) -> None:
        self._client = client or CoinMarketCapClient()

    def fetch_all(self, ctx: RunContext) -> CoinMarketCapSnapshots:
        response = self._client.get_latest()
        _validate_status(response.get("status"))
        data = _mapping(response.get("data"), "data")
        quote = _mapping(data.get("quote"), "data.quote")
        usd = _mapping(quote.get("USD"), "data.quote.USD")

        market_cap = _positive_float(
            usd.get("total_market_cap"), "data.quote.USD.total_market_cap"
        )
        dominance = _bounded_float(
            data.get("btc_dominance"),
            "data.btc_dominance",
            minimum=0.0,
            maximum=100.0,
        )
        change_24h = _market_cap_change_24h(usd, market_cap)
        as_of_dt, as_of = _iso_timestamp(data.get("last_updated"), "data.last_updated")
        age_seconds = (ctx.now.astimezone(timezone.utc) - as_of_dt).total_seconds()
        is_stale = age_seconds > _STALE_AFTER_SECONDS
        stale_reason = "coinmarketcap_global_stale" if is_stale else None

        dominance_payload: dict[str, object] = {
            "as_of": as_of,
            "btc_dominance": dominance,
        }
        global_mcap_payload: dict[str, object] = {
            "as_of": as_of,
            "total_market_cap_usd": market_cap,
            "market_cap_change_24h": change_24h,
        }
        total_mcap_payload: dict[str, object] = {
            "as_of": as_of,
            "value": market_cap,
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
        return CoinMarketCapSnapshots(
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
        source_id="coinmarketcap",
        symbol=symbol,
        payload=payload,
        as_of=as_of,
        is_stale=is_stale,
        stale_reason=stale_reason,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _validate_status(value: object) -> None:
    if value is None:
        return
    status = _mapping(value, "status")
    error_code = status.get("error_code")
    if error_code not in (None, 0, "0"):
        message = status.get("error_message")
        raise RuntimeError(f"CoinMarketCap API error {error_code}: {message}")


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"CoinMarketCap field {field} missing or invalid")
    return cast(dict[str, Any], value)


def _float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"CoinMarketCap field {field} missing or invalid")
    return float(value)


def _positive_float(value: object, field: str) -> float:
    result = _float(value, field)
    if result <= 0:
        raise RuntimeError(f"CoinMarketCap field {field} must be positive")
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
        raise RuntimeError(f"CoinMarketCap field {field} out of range")
    return result


def _market_cap_change_24h(usd: dict[str, Any], current: float) -> float:
    percentage = usd.get("total_market_cap_yesterday_percentage_change")
    if isinstance(percentage, (int, float)) and not isinstance(percentage, bool):
        return float(percentage)
    yesterday = _positive_float(
        usd.get("total_market_cap_yesterday"),
        "data.quote.USD.total_market_cap_yesterday",
    )
    return (current - yesterday) / yesterday * 100.0


def _iso_timestamp(value: object, field: str) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise RuntimeError(f"CoinMarketCap field {field} missing or invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"CoinMarketCap field {field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"CoinMarketCap field {field} has no timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc, utc.isoformat().replace("+00:00", "Z")


def enrich_total_mcap_history(
    snapshot: RawSnapshot,
    samples: list[TotalMcapSample],
) -> RawSnapshot:
    """Attach bounded real closes and 7d/30d changes without estimating missing history."""
    current_dt, _ = _iso_timestamp(snapshot.as_of, "snapshot.as_of")
    parsed_samples = _ordered_samples(samples, current_dt)[-_HISTORY_LIMIT:]
    payload = dict(snapshot.payload)
    changes_raw = payload.get("horizon_changes")
    changes = dict(changes_raw) if isinstance(changes_raw, dict) else {}
    changes["6h"] = None
    changes["7d"] = _historical_change(parsed_samples, current_dt, days=7)
    changes["30d"] = _historical_change(parsed_samples, current_dt, days=30)
    payload["horizon_changes"] = changes
    payload["closes"] = [sample.value for _, sample in parsed_samples]
    payload["history_as_of"] = [sample.as_of for _, sample in parsed_samples]
    payload["data_gaps"] = [
        gap
        for gap, available in (
            ("missing_6h_change", False),
            ("missing_7d_change", changes["7d"] is not None),
            ("missing_30d_change", changes["30d"] is not None),
        )
        if not available
    ]
    return snapshot.model_copy(
        update={"payload": payload, "content_hash": content_hash(payload)}
    )


def _ordered_samples(
    samples: list[TotalMcapSample], current: datetime
) -> list[tuple[datetime, TotalMcapSample]]:
    parsed: list[tuple[datetime, TotalMcapSample]] = []
    for sample in samples:
        sample_dt, _ = _iso_timestamp(sample.as_of, "sample.as_of")
        if sample.symbol == "TOTAL_MCAP" and sample_dt <= current:
            parsed.append((sample_dt, sample))
    return sorted(parsed, key=lambda item: item[0])


def _historical_change(
    samples: list[tuple[datetime, TotalMcapSample]],
    current: datetime,
    *,
    days: int,
) -> float | None:
    if not samples:
        return None
    target = current - timedelta(days=days)
    sample_dt, sample = min(samples, key=lambda item: abs(item[0] - target))
    if abs(sample_dt - target) > _HISTORY_TOLERANCE:
        return None
    current_value = samples[-1][1].value
    return (current_value - sample.value) / sample.value * 100.0
