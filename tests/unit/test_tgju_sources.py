"""Offline contract tests for the hybrid dollar and TGJU oil adapters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.enums import TriggerType
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real.tgju_dollar import (
    HybridUsdIrrSource,
    TgjuDollarSource,
)
from market_state_engine.ingestion.real.tgju_oil import TgjuOilSource


def _context() -> RunContext:
    return RunContext(
        run_id="01J8ZK3W9P4Q5R6S7T8U9V0W1X",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 14, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def _history(base: float, count: int = 140) -> list[object]:
    return [
        [
            f"{base + i:,.2f}",
            f"{base + i - 2:,.2f}",
            f"{base + i + 3:,.2f}",
            f"{base + i + 1:,.2f}",
            "0",
            "0%",
            f"2026/01/{(count - i - 1) % 28 + 1:02d}",
            "1404/10/01",
        ]
        for i in range(count)
    ]


def _spot(value: float = 185_000.0) -> RawSnapshot:
    payload: dict[str, object] = {
        "as_of": "2026-08-14T10:00:00Z",
        "value": value,
        "currency": "IRT",
    }
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


class _SpotSource:
    def __init__(self, snapshot: RawSnapshot | None = None, error: Exception | None = None) -> None:
        self._snapshot = snapshot or _spot()
        self._error = error

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if self._error is not None:
            raise self._error
        return self._snapshot


class _DollarClient:
    def __init__(self, *, history_error: Exception | None = None) -> None:
        self._history_error = history_error

    def fetch_live(self) -> dict[str, object]:
        return {
            "p": "1,850,000",
            "h": "1,880,000",
            "l": "1,840,000",
            "ts": "2026-08-10 13:30:00",
        }

    def fetch_history(self) -> list[object]:
        if self._history_error is not None:
            raise self._history_error
        return _history(1_700_000.0)


class _OilClient:
    def fetch_live(self) -> dict[str, object]:
        return {
            "p": "81.73",
            "h": "84.58",
            "l": "81.21",
            "ts": "2026-08-14 13:30:00",
        }

    def fetch_history(self) -> list[object]:
        return _history(70.0)


def test_hybrid_dollar_uses_kifpool_value_and_tgju_history() -> None:
    source = HybridUsdIrrSource(_SpotSource(), _DollarClient())
    snapshot = source.fetch_series("USD_IRR", _context())

    assert snapshot.source_id == "kifpool_tgju"
    assert snapshot.payload["currency"] == "IRT"
    assert snapshot.payload["value"] == 185_000.0
    assert snapshot.as_of == "2026-08-14T10:00:00Z"
    assert len(snapshot.payload["closes"]) == 130  # type: ignore[arg-type]
    assert snapshot.payload["closes"][-1] != 185_000.0  # type: ignore[index]
    assert snapshot.deviation_flags[0]["code"] == "cross_source_price_deviation"
    assert snapshot.content_hash == content_hash(snapshot.payload)


def test_hybrid_dollar_does_not_flag_small_deviation() -> None:
    source = HybridUsdIrrSource(
        _SpotSource(_spot(170_000.0)),
        _DollarClient(),
        deviation_threshold_pct=2.0,
    )
    snapshot = source.fetch_series("USD_IRR", _context())
    assert snapshot.deviation_flags == []


def test_hybrid_dollar_falls_back_to_stale_tgju_snapshot() -> None:
    source = HybridUsdIrrSource(
        _SpotSource(error=RuntimeError("kifpool down")),
        _DollarClient(),
        stale_after_minutes=60,
    )
    snapshot = source.fetch_series("USD_IRR", _context())

    assert snapshot.source_id == "tgju"
    assert snapshot.payload["value"] == 185_000.0
    assert len(snapshot.payload["closes"]) == 130  # type: ignore[arg-type]
    assert snapshot.is_stale is True
    assert snapshot.stale_reason is not None


def test_hybrid_dollar_history_failure_keeps_one_real_spot() -> None:
    source = HybridUsdIrrSource(
        _SpotSource(),
        _DollarClient(history_error=RuntimeError("history down")),
    )
    snapshot = source.fetch_series("USD_IRR", _context())

    assert snapshot.source_id == "kifpool"
    assert snapshot.payload["closes"] == [185_000.0]
    assert snapshot.payload["data_gaps"] == ["tgju_history_unavailable"]
    assert snapshot.deviation_flags == []


def test_tgju_oil_emits_usd_history_and_hash() -> None:
    source = TgjuOilSource(_OilClient())
    snapshot = source.fetch("WTI", _context())

    assert snapshot.source_id == "tgju"
    assert snapshot.symbol == "WTI"
    assert snapshot.payload["currency"] == "USD"
    assert snapshot.payload["value"] == 81.73
    assert len(snapshot.payload["closes"]) == 130  # type: ignore[arg-type]
    assert snapshot.content_hash == content_hash(snapshot.payload)


@pytest.mark.parametrize(
    ("source", "symbol"),
    [
        (HybridUsdIrrSource(_SpotSource(), _DollarClient()), "BTC"),
        (TgjuDollarSource(_DollarClient()), "GOLD"),
        (TgjuOilSource(_OilClient()), "ETH"),
    ],
)
def test_tgju_sources_reject_other_assets(source: object, symbol: str) -> None:
    with pytest.raises(KeyError):
        source.fetch_series(symbol, _context())  # type: ignore[attr-defined]


def test_tgju_oil_requires_130_valid_history_rows() -> None:
    class _ShortOilClient(_OilClient):
        def fetch_history(self) -> list[object]:
            return _history(70.0, count=129)

    source = TgjuOilSource(_ShortOilClient())
    with pytest.raises(RuntimeError, match="at least 130"):
        source.fetch_series("WTI", _context())
