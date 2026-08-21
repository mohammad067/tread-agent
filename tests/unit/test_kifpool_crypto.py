"""Kifpool BTC/ETH spot normalization tests."""

from __future__ import annotations

from datetime import datetime, timezone

from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real.kifpool_crypto import KifpoolCryptoPriceSource


class _Client:
    def fetch_symbol(self, api_symbol: str) -> dict[str, object]:
        return {"price": "65000.5", "high": "66000", "low": "64000", "volume": "9"}


def _context() -> RunContext:
    return RunContext(
        run_id="kifpool-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def test_kifpool_is_spot_only_and_deterministic() -> None:
    source = KifpoolCryptoPriceSource(_Client())  # type: ignore[arg-type]

    snapshot = source.fetch_series("BTC", _context())

    assert snapshot.source_id == "kifpool"
    assert snapshot.as_of == "2026-08-21T08:00:00Z"
    assert snapshot.payload["value"] == 65000.5
    assert snapshot.payload["currency"] == "USD"
    assert snapshot.payload["source_price_field"] == "price"
    assert snapshot.payload["source_quote_method"] == "provider_price_field_unspecified"
    assert "closes" not in snapshot.payload
    assert "highs" not in snapshot.payload
    assert "lows" not in snapshot.payload
    assert "volumes" not in snapshot.payload
