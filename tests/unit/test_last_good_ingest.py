"""Last-good real-ingest recording and fallback behavior."""

from __future__ import annotations

import logging

import pytest

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.ingestion.real.provider import (
    _load_last_good,
    _record_last_good,
)


class _Store:
    def __init__(self) -> None:
        self.snapshot: RawSnapshot | None = None

    def record(self, snapshot: RawSnapshot) -> None:
        self.snapshot = snapshot

    def get(self, symbol: str) -> RawSnapshot | None:
        if self.snapshot is None or self.snapshot.symbol != symbol:
            return None
        return self.snapshot.model_copy(
            update={"is_stale": True, "stale_reason": "last_good"}
        )


def _live() -> RawSnapshot:
    return RawSnapshot(
        source_id="coinmarketcap",
        symbol="TOTAL_MCAP",
        payload={"value": 1_000_000.0, "currency": "USD"},
        as_of="2026-08-16T00:00:00Z",
        is_stale=False,
        stale_reason=None,
        deviation_flags=[],
        content_hash="snapshot-hash",
    )


def test_success_is_recorded_then_failure_loads_stale_last_good(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Store()
    live = _live()

    _record_last_good(store, live)
    with caplog.at_level(logging.WARNING, logger="ingestion.real"):
        fallback = _load_last_good(store, "TOTAL_MCAP")

    assert store.snapshot == live
    assert fallback is not None
    assert fallback.payload == live.payload
    assert fallback.is_stale is True
    assert fallback.stale_reason == "last_good"
    assert "last_good_used symbol=TOTAL_MCAP source=coinmarketcap" in caplog.text
