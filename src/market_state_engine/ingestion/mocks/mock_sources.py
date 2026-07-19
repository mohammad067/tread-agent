"""Deterministic, offline mock ingestors.

Given fixed inputs they always return the same snapshots — no network, no clock, no randomness —
so the whole deterministic pipeline is replay-testable. Payloads carry OHLCV-style series and
price data the FeatureEngine consumes.
"""

from __future__ import annotations

from typing import Any

from market_state_engine.core.dtos import MacroEvent, NewsItem, RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext


def _snapshot(
    source_id: str, symbol: str | None, payload: dict[str, Any], as_of: str
) -> RawSnapshot:
    return RawSnapshot(
        source_id=source_id,
        symbol=symbol,
        payload=payload,
        as_of=as_of,
        is_stale=False,
        stale_reason=None,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


class MockPriceSource:
    """Returns a deterministic price + OHLCV-ish series per symbol."""

    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data

    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        payload = self._data[symbol]
        return _snapshot("mock_price", symbol, payload, str(payload["as_of"]))


class MockIndicatorInputSource:
    def __init__(self, series: dict[str, dict[str, Any]]) -> None:
        self._series = series

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        payload = self._series[symbol]
        return _snapshot("mock_indicator", symbol, payload, str(payload["as_of"]))


class MockFearGreedSource:
    def __init__(self, value: int, as_of: str) -> None:
        self._payload: dict[str, Any] = {"value": value, "as_of": as_of}
        self._as_of = as_of

    def fetch(self, ctx: RunContext) -> RawSnapshot:
        return _snapshot("mock_fear_greed", None, self._payload, self._as_of)


class MockDominanceSource:
    def __init__(self, btc_dominance: float, as_of: str) -> None:
        self._payload: dict[str, Any] = {"btc_dominance": btc_dominance, "as_of": as_of}
        self._as_of = as_of

    def fetch(self, ctx: RunContext) -> RawSnapshot:
        return _snapshot("mock_dominance", None, self._payload, self._as_of)


class MockTotalMcapSource:
    def __init__(self, total_market_cap_usd: float, as_of: str) -> None:
        self._payload: dict[str, Any] = {
            "total_market_cap_usd": total_market_cap_usd,
            "as_of": as_of,
        }
        self._as_of = as_of

    def fetch(self, ctx: RunContext) -> RawSnapshot:
        return _snapshot("mock_total_mcap", None, self._payload, self._as_of)


class MockNewsSource:
    def __init__(self, items: list[NewsItem]) -> None:
        self._items = items

    def fetch_items(self, ctx: RunContext) -> list[NewsItem]:
        return list(self._items)


class MockEventSource:
    def __init__(self, events: list[MacroEvent]) -> None:
        self._events = events

    def fetch_events(self, ctx: RunContext) -> list[MacroEvent]:
        return list(self._events)
