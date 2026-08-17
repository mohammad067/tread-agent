"""Database-backed cache of the latest successful real snapshot per symbol."""

from __future__ import annotations

from market_state_engine.core.dtos import RawSnapshot

from .repositories import LastGoodSnapshotRepository
from .session import Database


class SqlLastGoodSnapshotStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, snapshot: RawSnapshot) -> None:
        with self._database.session() as session:
            LastGoodSnapshotRepository(session).upsert(snapshot)

    def get(self, symbol: str) -> RawSnapshot | None:
        with self._database.session() as session:
            return LastGoodSnapshotRepository(session).get(symbol)
