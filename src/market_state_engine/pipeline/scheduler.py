"""Scheduler & trigger (pipelines.md §1, module-catalog E2).

Assigns run identity (``run_id`` ULID, ``run_sequence``, ``trigger_type``) and hands off to the
``RunService`` (E1). Two trigger paths — scheduled (cron) and event/manual — converge on one
executor so the lifecycle is identical. A replay path re-executes over recorded inputs. Overlapping
runs are prevented with a non-reentrant lock: a second trigger while one is in flight is refused
(single-node, in-process — challenge A1). Supports multiple assets implicitly (the pipeline always
scores all six configured assets).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import Lock

from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import RegimeState, TriggerType
from market_state_engine.core.models import TriggerDetail
from market_state_engine.core.run_context import RunContext

from .orchestrator import IngestBundle, new_run_id
from .runner import RunService, RunSummary


class ExecutionMode(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    REPLAY = "replay"


@dataclass(frozen=True)
class OverlapError(Exception):
    """A run was requested while another was already in progress (overlap prevented)."""

    message: str = "a run is already in progress"


# Provider of the raw inputs + previous regime for a run — the ingestion seam (mock/live/replay).
IngestProvider = Callable[[RunContext], IngestBundle]
PreviousStateProvider = Callable[[], RegimeState | None]


class Scheduler:
    def __init__(
        self,
        run_service: RunService,
        ingest_provider: IngestProvider,
        clock: Callable[[], datetime],
        *,
        run_sequence_provider: Callable[[], int] | None = None,
        previous_state_provider: PreviousStateProvider | None = None,
        versions: dict[str, str] | None = None,
    ) -> None:
        self._run_service = run_service
        self._ingest = ingest_provider
        self._clock = clock
        self._seq = run_sequence_provider or _counter()
        self._prev = previous_state_provider or (lambda: None)
        self._versions = versions or {}
        self._lock = Lock()

    def trigger(
        self,
        mode: ExecutionMode = ExecutionMode.SCHEDULED,
        *,
        run_id: str | None = None,
        trigger_type: TriggerType | None = None,
        trigger_detail: TriggerDetail | None = None,
        events: list[MacroEvent] | None = None,
    ) -> RunSummary:
        """Assign identity + execute one run. Refuses if another run is in flight (overlap)."""
        if not self._lock.acquire(blocking=False):
            raise OverlapError()
        try:
            resolved_trigger_type = trigger_type or (
                TriggerType.EVENT if mode is ExecutionMode.MANUAL else TriggerType.SCHEDULED
            )
            ctx = RunContext(
                run_id=run_id or new_run_id(),
                run_sequence=self._seq(),
                trigger_type=resolved_trigger_type,
                trigger_detail=trigger_detail,
                now=self._clock(),
                previous_state=self._prev(),
                versions=self._versions,
            )
            ingest = self._ingest(ctx)
            if events is not None:
                ingest = IngestBundle(
                    indicator_snapshots=ingest.indicator_snapshots,
                    price_snapshots=ingest.price_snapshots,
                    global_snapshots=ingest.global_snapshots,
                    events=list(events),
                    news_items=ingest.news_items,
                )
            return self._run_service.execute(ctx, ingest)
        finally:
            self._lock.release()

    def run_scheduled(self) -> RunSummary:
        return self.trigger(ExecutionMode.SCHEDULED)

    def run_manual(self, run_id: str | None = None) -> RunSummary:
        return self.trigger(ExecutionMode.MANUAL, run_id=run_id)

    def run_event(
        self,
        events: list[MacroEvent],
        *,
        event_id: str,
        debounced_events: int,
        run_id: str | None = None,
    ) -> RunSummary:
        """Run over the exact persisted MacroEvents selected by the Event Trigger."""
        return self.trigger(
            ExecutionMode.MANUAL,
            run_id=run_id,
            trigger_type=TriggerType.EVENT,
            trigger_detail=TriggerDetail(
                event_id=event_id,
                debounced_events=debounced_events,
            ),
            events=events,
        )

    def run_replay(
        self,
        run_id: str,
        *,
        trigger_type: TriggerType = TriggerType.SCHEDULED,
        trigger_detail: TriggerDetail | None = None,
    ) -> RunSummary:
        return self.trigger(
            ExecutionMode.REPLAY,
            run_id=run_id,
            trigger_type=trigger_type,
            trigger_detail=trigger_detail,
        )


def _counter() -> Callable[[], int]:
    state = {"n": 0}

    def _next() -> int:
        state["n"] += 1
        return state["n"]

    return _next
