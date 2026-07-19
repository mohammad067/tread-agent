"""Ingestion source ports (Protocols) — the boundary between the world and the deterministic core.

Every source returns immutable ``RawSnapshot``(s) (or raw domain records for news/events). Real
adapters (kifpool, crypto venues, feeds) arrive in M5; only deterministic mocks exist in M3. The
core depends on these Protocols, never on a concrete source.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from market_state_engine.core.dtos import MacroEvent, NewsItem, RawSnapshot
from market_state_engine.core.run_context import RunContext


@runtime_checkable
class PriceSource(Protocol):
    def fetch(self, symbol: str, ctx: RunContext) -> RawSnapshot: ...


@runtime_checkable
class IndicatorInputSource(Protocol):
    def fetch_series(self, symbol: str, ctx: RunContext) -> RawSnapshot: ...


@runtime_checkable
class FearGreedSource(Protocol):
    def fetch(self, ctx: RunContext) -> RawSnapshot: ...


@runtime_checkable
class DominanceSource(Protocol):
    def fetch(self, ctx: RunContext) -> RawSnapshot: ...


@runtime_checkable
class TotalMcapSource(Protocol):
    def fetch(self, ctx: RunContext) -> RawSnapshot: ...


@runtime_checkable
class NewsSource(Protocol):
    def fetch_items(self, ctx: RunContext) -> list[NewsItem]: ...


@runtime_checkable
class EventSource(Protocol):
    def fetch_events(self, ctx: RunContext) -> list[MacroEvent]: ...
