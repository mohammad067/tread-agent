"""Real ingest uses only live snapshots or persisted last-good snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.enums import TriggerType
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real import provider
from market_state_engine.ingestion.real.coinmarketcap import CoinMarketCapSnapshots

_SYMBOLS = ("BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP")


class _LastGoodStore:
    def __init__(self, snapshots: list[RawSnapshot] | None = None) -> None:
        self.snapshots = {
            snapshot.symbol: snapshot
            for snapshot in snapshots or []
            if snapshot.symbol is not None
        }

    def record(self, snapshot: RawSnapshot) -> None:
        assert snapshot.symbol is not None
        self.snapshots[snapshot.symbol] = snapshot

    def get(self, symbol: str) -> RawSnapshot | None:
        snapshot = self.snapshots.get(symbol)
        if snapshot is None:
            return None
        return snapshot.model_copy(
            update={"is_stale": True, "stale_reason": "last_good"}
        )


class _AssetSource:
    def __init__(self, symbols: set[str], source_id: str, *, failing: bool) -> None:
        self._symbols = symbols
        self._source_id = source_id
        self._failing = failing

    def supports(self, symbol: str) -> bool:
        return symbol in self._symbols

    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot:
        if self._failing:
            raise RuntimeError(f"{self._source_id} unavailable")
        return _snapshot(self._source_id, symbol)


class _CoinMarketCapSource:
    def __init__(self, *, failing: bool) -> None:
        self._failing = failing

    def fetch_all(self, ctx: RunContext) -> CoinMarketCapSnapshots:
        if self._failing:
            raise RuntimeError("coinmarketcap unavailable")
        return CoinMarketCapSnapshots(
            dominance=_global_snapshot("btc_dominance", 55.0),
            global_mcap=_global_snapshot("total_market_cap_usd", 2_000_000.0),
            total_mcap=_snapshot("coinmarketcap", "TOTAL_MCAP", 2_000_000.0),
        )


class _FearGreedSource:
    def __init__(self, *, failing: bool) -> None:
        self._failing = failing

    def fetch(self, ctx: RunContext) -> RawSnapshot:
        if self._failing:
            raise RuntimeError("fear and greed unavailable")
        return _global_snapshot("value", 45.0, source_id="alternative_me")


class _NewsSource:
    def fetch_items(self, ctx: RunContext) -> list[object]:
        return []


def _ctx() -> RunContext:
    return RunContext(
        run_id="real-ingest-test",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
        previous_state=None,
        versions={},
    )


def _snapshot(source_id: str, symbol: str, value: float = 100.0) -> RawSnapshot:
    currency = "IRT" if symbol == "USD_IRR" else "USD"
    payload: dict[str, object] = {
        "as_of": "2026-08-19T07:59:00Z",
        "value": value,
        "currency": currency,
        "closes": [value] * 130,
        "highs": [value] * 130,
        "lows": [value] * 130,
        "volumes": [1.0] * 130,
    }
    return RawSnapshot(
        source_id=source_id,
        symbol=symbol,
        payload=payload,
        as_of="2026-08-19T07:59:00Z",
        is_stale=False,
        stale_reason=None,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _global_snapshot(
    field: str, value: float, *, source_id: str = "coinmarketcap"
) -> RawSnapshot:
    payload: dict[str, object] = {field: value, "as_of": "2026-08-19T07:59:00Z"}
    return RawSnapshot(
        source_id=source_id,
        symbol=None,
        payload=payload,
        as_of="2026-08-19T07:59:00Z",
        is_stale=False,
        stale_reason=None,
        deviation_flags=[],
        content_hash=content_hash(payload),
    )


def _patch_sources(monkeypatch: pytest.MonkeyPatch, *, failing: bool) -> None:
    monkeypatch.setattr(provider, "CoinGeckoClient", object)
    monkeypatch.setattr(
        provider,
        "CoinGeckoPriceSource",
        lambda client: _AssetSource({"BTC", "ETH", "GOLD"}, "coingecko", failing=failing),
    )
    monkeypatch.setattr(
        provider,
        "KifpoolCryptoPriceSource",
        lambda: _AssetSource({"BTC", "ETH"}, "kifpool", failing=failing),
    )
    monkeypatch.setattr(
        provider,
        "HybridUsdIrrSource",
        lambda: _AssetSource({"USD_IRR"}, "kifpool_tgju", failing=failing),
    )
    monkeypatch.setattr(
        provider,
        "TgjuOilSource",
        lambda: _AssetSource({"WTI"}, "tgju", failing=failing),
    )
    monkeypatch.setattr(
        provider, "CoinMarketCapGlobalSource", lambda: _CoinMarketCapSource(failing=failing)
    )
    monkeypatch.setattr(provider, "FearGreedSource", lambda: _FearGreedSource(failing=failing))
    monkeypatch.setattr(provider, "RssNewsSource", _NewsSource)
    monkeypatch.setattr(provider, "load_us_cpi_event", lambda root: None)


def test_live_success_uses_real_snapshots_and_records_last_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sources(monkeypatch, failing=False)
    store = _LastGoodStore()

    bundle = provider.real_ingest_provider(_ctx(), last_good_store=store)

    assert set(bundle.price_snapshots) == set(_SYMBOLS)
    assert set(bundle.indicator_snapshots) == set(_SYMBOLS)
    assert all(snapshot.source_id != "mock" for snapshot in bundle.price_snapshots.values())
    assert set(store.snapshots) == {*_SYMBOLS, "FEAR_GREED"}
    assert bundle.global_snapshots["fear_greed"].source_id == "alternative_me"


def test_live_failure_uses_stale_last_good_without_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sources(monkeypatch, failing=True)
    stored = [_snapshot("persisted_real", symbol) for symbol in _SYMBOLS]
    fear_greed = _global_snapshot("value", 40.0, source_id="alternative_me").model_copy(
        update={"symbol": "FEAR_GREED"}
    )
    store = _LastGoodStore([*stored, fear_greed])

    bundle = provider.real_ingest_provider(_ctx(), last_good_store=store)

    assert set(bundle.price_snapshots) == set(_SYMBOLS)
    assert all(snapshot.source_id != "mock" for snapshot in bundle.price_snapshots.values())
    assert all(snapshot.is_stale for snapshot in bundle.price_snapshots.values())
    assert all(
        snapshot.stale_reason == "last_good" for snapshot in bundle.price_snapshots.values()
    )
    fallback_fear_greed = bundle.global_snapshots["fear_greed"]
    assert fallback_fear_greed.symbol is None
    assert fallback_fear_greed.is_stale is True
    assert fallback_fear_greed.stale_reason == "last_good"


def test_live_failure_without_last_good_emits_no_mock_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sources(monkeypatch, failing=True)

    bundle = provider.real_ingest_provider(
        _ctx(), last_good_store=_LastGoodStore()
    )

    assert bundle.price_snapshots == {}
    assert bundle.indicator_snapshots == {}
    assert bundle.global_snapshots == {}
    assert all(
        snapshot.source_id != "mock"
        for snapshots in (
            bundle.price_snapshots,
            bundle.indicator_snapshots,
            bundle.global_snapshots,
        )
        for snapshot in snapshots.values()
    )
