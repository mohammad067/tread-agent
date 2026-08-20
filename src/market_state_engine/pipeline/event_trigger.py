"""Persistent MacroEvent trigger with deterministic cooldown and aggregation.

The accepted MacroEvents and trigger decisions are reconstructed from the database on every
submission. This keeps debounce state restart-safe without a mutable in-memory queue. A leading
event runs immediately; later events inside the configured cooldown remain pending and are folded
into the first event run requested after the window expires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from market_state_engine.core.dtos import MacroEvent
from market_state_engine.persistence.repositories import (
    EventLogRepository,
    MacroEventRepository,
)
from market_state_engine.persistence.session import Database

from .events import EventRecorder, EventType
from .scheduler import OverlapError, Scheduler


@dataclass(frozen=True)
class EventTriggerResult:
    event_id: str
    accepted: bool
    surprise: float | None
    debounced: bool
    run_id: str | None = None
    run_status: str | None = None


class EventTrigger:
    """Persist one event and, when eligible, execute the exact pending event batch."""

    def __init__(
        self,
        database: Database,
        scheduler: Scheduler,
        clock: Callable[[], datetime],
        *,
        cooldown_minutes: int,
    ) -> None:
        self._database = database
        self._scheduler = scheduler
        self._clock = clock
        self._cooldown = timedelta(minutes=cooldown_minutes)
        self._lock = Lock()

    def submit(self, event: MacroEvent, *, raw: dict[str, object]) -> EventTriggerResult:
        """Idempotently persist an event and invoke the event path when cooldown permits."""
        with self._lock:
            now = _aware_utc(self._clock())
            surprise = _surprise(event)
            with self._database.session() as session:
                row, created = MacroEventRepository(session).add_if_absent(
                    event,
                    surprise=surprise,
                    raw=raw,
                    ingested_at=_iso(now),
                )

            if not created:
                return EventTriggerResult(
                    event_id=row.event_id,
                    accepted=True,
                    surprise=row.surprise,
                    debounced=False,
                )

            self._record(
                EventType.EVENT_ACCEPTED,
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                },
            )

            # Consensus-only calendar entries remain auditable but cannot drive surprise rules.
            if event.actual is None:
                return EventTriggerResult(event.event_id, True, None, False)

            pending = self._pending_complete_events()
            last_triggered_at = self._last_triggered_at()
            if last_triggered_at is not None and now < last_triggered_at + self._cooldown:
                self._record(
                    EventType.EVENT_DEBOUNCED,
                    {
                        "event_id": event.event_id,
                        "pending_events": len(pending),
                        "cooldown_until": _iso(last_triggered_at + self._cooldown),
                    },
                )
                return EventTriggerResult(event.event_id, True, surprise, True)

            return self._execute_pending(event, pending)

    def _execute_pending(
        self,
        submitted: MacroEvent,
        pending: list[MacroEvent],
    ) -> EventTriggerResult:
        if not pending:
            return EventTriggerResult(submitted.event_id, True, None, False)

        primary = pending[0]
        event_ids = [event.event_id for event in pending]
        try:
            summary = self._scheduler.run_event(
                pending,
                event_id=primary.event_id,
                debounced_events=len(pending) - 1,
            )
        except OverlapError:
            self._record(
                EventType.EVENT_DEBOUNCED,
                {
                    "event_id": submitted.event_id,
                    "pending_events": len(pending),
                    "reason": "run_overlap",
                },
            )
            return EventTriggerResult(submitted.event_id, True, None, True)
        except Exception as exc:
            self._record(
                EventType.EVENT_FAILED,
                {
                    "event_id": submitted.event_id,
                    "event_ids": event_ids,
                    "error": type(exc).__name__,
                },
            )
            return EventTriggerResult(
                submitted.event_id,
                True,
                _surprise(submitted),
                False,
                run_status="failed",
            )

        self._record(
            EventType.EVENT_TRIGGERED,
            {
                "event_id": primary.event_id,
                "event_ids": event_ids,
                "debounced_events": len(pending) - 1,
                "status": summary.status,
            },
            run_id=summary.run_id,
        )
        return EventTriggerResult(
            submitted.event_id,
            True,
            _surprise(submitted),
            False,
            run_id=summary.run_id,
            run_status=summary.status,
        )

    def _pending_complete_events(self) -> list[MacroEvent]:
        with self._database.session() as session:
            events = MacroEventRepository(session).list_events()
            triggered_rows = EventLogRepository(session).list_by_type(
                EventType.EVENT_TRIGGERED.value
            )
        triggered = {
            str(event_id) for row in triggered_rows for event_id in _event_ids(row.payload)
        }
        return [
            event
            for event in events
            if event.actual is not None and event.event_id not in triggered
        ]

    def _last_triggered_at(self) -> datetime | None:
        with self._database.session() as session:
            rows = EventLogRepository(session).list_by_type(EventType.EVENT_TRIGGERED.value)
        if not rows:
            return None
        return _parse_iso(rows[-1].created_at)

    def _record(
        self,
        event_type: EventType,
        payload: dict[str, object],
        *,
        run_id: str | None = None,
    ) -> None:
        with self._database.session() as session:
            EventRecorder(EventLogRepository(session), self._clock).record(
                event_type,
                payload,
                run_id=run_id,
            )


def _event_ids(payload: dict[str, object]) -> list[object]:
    value = payload.get("event_ids")
    return list(value) if isinstance(value, list) else []


def _surprise(event: MacroEvent) -> float | None:
    return event.actual - event.consensus if event.actual is not None else None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: str) -> datetime:
    return _aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")
