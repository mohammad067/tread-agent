"""Database-backed TOTAL_MCAP history store used by the real ingestion composition."""

from __future__ import annotations

from market_state_engine.core.dtos import TotalMcapSample

from .repositories import TotalMcapSampleRepository
from .session import Database


class SqlTotalMcapHistoryStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def record_and_list(
        self, sample: TotalMcapSample, *, limit: int = 130
    ) -> list[TotalMcapSample]:
        with self._database.session() as session:
            repository = TotalMcapSampleRepository(session)
            repository.upsert(sample)
            return repository.list_recent(sample.symbol, limit=limit)
