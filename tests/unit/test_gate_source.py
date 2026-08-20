"""Gate keyless BTC/ETH adapter tests."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real.gate import GateClient, GateCryptoPriceSource


class _HttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _HttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Client:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int]] = []

    def fetch_candles(self, currency_pair: str, *, limit: int) -> list[list[object]]:
        self.calls.append((currency_pair, limit))
        return self.rows


def _context() -> RunContext:
    return RunContext(
        run_id="gate-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 20, 12, 34, 56, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def _hourly_rows(hours: int = 800) -> list[list[object]]:
    start = 1_782_000_000
    rows: list[list[object]] = []
    for index in range(hours):
        price = 70_000.0 + index
        rows.append(
            [
                str(start + index * 3600),
                "1000.0",
                str(price),
                str(price + 10.0),
                str(price - 10.0),
                str(price - 1.0),
                "2.5",
                "true",
            ]
        )
    return rows


@pytest.mark.parametrize(("symbol", "pair"), [("BTC", "BTC_USDT"), ("ETH", "ETH_USDT")])
def test_gate_builds_replayable_six_hour_series(symbol: str, pair: str) -> None:
    client = _Client(_hourly_rows())
    snapshot = GateCryptoPriceSource(client).fetch_series(symbol, _context())  # type: ignore[arg-type]

    assert client.calls == [(pair, 800)]
    assert snapshot.source_id == "gate"
    assert snapshot.symbol == symbol
    assert snapshot.as_of == "2026-08-20T12:34:56Z"
    assert snapshot.is_stale is False
    assert snapshot.payload["source_pair"] == pair
    assert snapshot.payload["source_quote_currency"] == "USDT"
    assert snapshot.payload["currency"] == "USD"
    assert snapshot.payload["quote_normalization"] == "USDT_USD_NOMINAL"
    assert len(snapshot.payload["closes"]) == 130  # type: ignore[arg-type]
    assert len(snapshot.payload["highs"]) == 130  # type: ignore[arg-type]
    assert len(snapshot.payload["lows"]) == 130  # type: ignore[arg-type]
    assert len(snapshot.payload["volumes"]) == 130  # type: ignore[arg-type]
    assert snapshot.payload["value"] == snapshot.payload["closes"][-1]  # type: ignore[index]


def test_gate_fetch_alias_uses_same_series_path() -> None:
    snapshot = GateCryptoPriceSource(_Client(_hourly_rows())).fetch(  # type: ignore[arg-type]
        "BTC", _context()
    )

    assert snapshot.symbol == "BTC"


def test_gate_supports_only_btc_and_eth() -> None:
    source = GateCryptoPriceSource(_Client(_hourly_rows()))  # type: ignore[arg-type]

    assert source.supports("BTC")
    assert source.supports("eth")
    assert not source.supports("GOLD")
    with pytest.raises(KeyError, match="only BTC/ETH"):
        source.fetch_series("GOLD", _context())


def test_gate_rejects_insufficient_history() -> None:
    source = GateCryptoPriceSource(_Client(_hourly_rows(12)))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="need 130"):
        source.fetch_series("BTC", _context())


def test_gate_rejects_malformed_candle() -> None:
    rows = _hourly_rows()
    rows[-1][2] = "not-a-price"
    source = GateCryptoPriceSource(_Client(rows))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="non-numeric candle"):
        source.fetch_series("BTC", _context())


def test_gate_rejects_short_and_non_positive_candles() -> None:
    with pytest.raises(RuntimeError, match="short candle"):
        GateCryptoPriceSource(_Client([["1"]])).fetch_series(  # type: ignore[arg-type]
            "BTC", _context()
        )

    rows = _hourly_rows()
    rows[-1][2] = "0"
    with pytest.raises(RuntimeError, match="invalid candle value"):
        GateCryptoPriceSource(_Client(rows)).fetch_series(  # type: ignore[arg-type]
            "BTC", _context()
        )


def test_gate_http_client_validates_response(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _hourly_rows(1)

    def _urlopen(request: urllib.request.Request, *, timeout: float) -> _HttpResponse:
        assert "currency_pair=BTC_USDT" in request.full_url
        assert timeout == 3.0
        return _HttpResponse(json.dumps(rows).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    assert GateClient(timeout_s=3.0).fetch_candles("BTC_USDT", limit=1) == rows

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(b"{}"),
    )
    with pytest.raises(RuntimeError, match="returned no candles"):
        GateClient().fetch_candles("BTC_USDT", limit=1)


def test_gate_http_client_wraps_transport_and_json_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _http_error(request: object, timeout: float) -> _HttpResponse:
        raise urllib.error.HTTPError("gate", 429, "rate limited", {}, io.BytesIO(b"rate"))

    monkeypatch.setattr(urllib.request, "urlopen", _http_error)
    with pytest.raises(RuntimeError, match="Gate HTTP 429"):
        GateClient().fetch_candles("BTC_USDT", limit=1)

    def _network_error(request: object, timeout: float) -> _HttpResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _network_error)
    with pytest.raises(RuntimeError, match="Gate network error"):
        GateClient().fetch_candles("BTC_USDT", limit=1)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _HttpResponse(b"not-json"),
    )
    with pytest.raises(RuntimeError, match="Gate invalid JSON"):
        GateClient().fetch_candles("BTC_USDT", limit=1)
