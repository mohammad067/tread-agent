"""OutcomeRecorder — persist execution outcomes to the append-only Event Log (module-catalog F1).

Records a typed outcome for every kind of execution the system performs — successful, degraded,
replay, evaluation, provider, and validation — so operators and the evaluation pipeline have a
durable, queryable trace. Outcomes are written as ``execution_outcome`` rows in the existing
``event_log`` table (its ``event_type``/``payload`` are free-form, so this needs no schema change
and adds no table). Append-only: outcomes are inserted, never updated. Time is injected.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from market_state_engine.observability.logging import get_logger
from market_state_engine.persistence.repositories import EventLogRepository
from market_state_engine.persistence.session import Database

_EVENT_TYPE = "execution_outcome"


class OutcomeKind(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    REPLAY = "replay"
    EVALUATION = "evaluation"
    PROVIDER = "provider"
    VALIDATION = "validation"


class OutcomeRecorder:
    def __init__(
        self,
        db: Database,
        clock: Callable[[], datetime],
        logger: Any | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._log = logger or get_logger("evaluation.outcomes")

    def record(
        self,
        kind: OutcomeKind,
        detail: dict[str, object] | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        payload: dict[str, object] = {"kind": kind.value, **(detail or {})}
        created_at = self._clock().isoformat().replace("+00:00", "Z")
        with self._db.session() as session:
            EventLogRepository(session).add(
                _EVENT_TYPE, payload, created_at=created_at, run_id=run_id
            )
        self._log.info("execution_outcome", run_id=run_id, **payload)

    # Convenience recorders (one per required outcome category) --------------------------
    def record_success(self, run_id: str, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.SUCCESS, detail, run_id=run_id)

    def record_degraded(self, run_id: str, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.DEGRADED, detail, run_id=run_id)

    def record_replay(self, run_id: str, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.REPLAY, detail, run_id=run_id)

    def record_evaluation(self, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.EVALUATION, detail)

    def record_provider(self, run_id: str, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.PROVIDER, detail, run_id=run_id)

    def record_validation(self, detail: dict[str, object] | None = None) -> None:
        self.record(OutcomeKind.VALIDATION, detail)

    # Read-back --------------------------------------------------------------------------
    def outcomes_for_run(self, run_id: str) -> list[dict[str, object]]:
        with self._db.session() as session:
            rows = EventLogRepository(session).list_for_run(run_id)
        return [dict(r.payload) for r in rows if r.event_type == _EVENT_TYPE]
