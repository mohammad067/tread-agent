"""CoinGecko BTC/ETH history normalization tests for ADR-009."""

from __future__ import annotations

from datetime import datetime, timezone

from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real.coingecko import CoinGeckoPriceSource


class _Client:
    def get_json(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, list[list[float]]]:
        prices = [[1_786_000_000_000.0 + index * 3600_000.0, 100.0 + index] for index in range(130)]
        volumes = [[row[0], 1_000.0 + index] for index, row in enumerate(prices)]
        return {"prices": prices, "total_volumes": volumes}


def _context() -> RunContext:
    return RunContext(
        run_id="coingecko-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def test_crypto_history_keeps_real_closes_without_estimated_candles() -> None:
    source = CoinGeckoPriceSource(_Client())  # type: ignore[arg-type]

    snapshot = source.fetch_series("BTC", _context())

    assert snapshot.payload["currency"] == "USD"
    assert snapshot.payload["source_quote_currency"] == "USD"
    assert snapshot.payload["quote_normalization"] == "COINGECKO_USD_NORMALIZED"
    assert len(snapshot.payload["closes"]) == 130  # type: ignore[arg-type]
    assert "highs" not in snapshot.payload
    assert "lows" not in snapshot.payload


def test_gold_path_remains_unchanged() -> None:
    source = CoinGeckoPriceSource(_Client())  # type: ignore[arg-type]

    snapshot = source.fetch_series("GOLD", _context())

    assert "highs" in snapshot.payload
    assert "lows" in snapshot.payload
