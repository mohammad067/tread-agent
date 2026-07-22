"""Execution-event recording (pipelines.md §7): persist every lifecycle event, structured-logged.

The Event Log captures a chronological trace of a run: start, finish, failures, degraded mode,
provider calls, replay, and scheduler events. Each event is written to the append-only ``event_log``
table (via the repository) and emitted as a structured log line with the ``run_id`` correlation key.
Time is injected so the trace is deterministic in tests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from market_state_engine.observability.logging import get_logger
from market_state_engine.persistence.repositories import EventLogRepository


class EventType(str, Enum):
    RUN_START = "run_start"
    RUN_FINISH = "run_finish"
    RUN_FAILURE = "run_failure"
    DEGRADED = "degraded"
    PROVIDER_CALL = "provider_call"
    REPLAY = "replay"
    SCHEDULER = "scheduler"


class EventRecorder:
    def __init__(
        self,
        repo: EventLogRepository,
        clock: Callable[[], datetime],
        logger: Any | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._log = logger or get_logger("pipeline.events")

    def record(
        self,
        event_type: EventType,
        payload: dict[str, object] | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        data = dict(payload or {})
        created_at = self._clock().isoformat().replace("+00:00", "Z")
        self._repo.add(event_type.value, data, created_at=created_at, run_id=run_id)
        self._log.info(event_type.value, run_id=run_id, **data)
