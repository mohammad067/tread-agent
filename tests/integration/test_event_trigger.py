"""MacroEvent persistence-to-pipeline integration, cooldown, restart, and audit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from market_state_engine.api.app import create_app
from market_state_engine.app.container import Container, build_container
from market_state_engine.persistence.repositories import EventLogRepository, RunRepository
from market_state_engine.pipeline.orchestrator import IngestBundle

from ._harness import REPO, SequencedFake, ingest_provider


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _container(clock: MutableClock, sqlite_path: str | None = None) -> Container:
    return build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=clock,
        sqlite_path=sqlite_path,
    )


def _submit(
    client: TestClient,
    event_id: str,
    event_type: str,
    scheduled_at: datetime,
    *,
    actual: float = 0.5,
) -> Response:
    return client.post(
        "/v1/events",
        json={
            "event_id": event_id,
            "event_type": event_type,
            "scheduled_at": scheduled_at.isoformat().replace("+00:00", "Z"),
            "consensus": 0.3,
            "actual": actual,
        },
        headers={"x-api-key": "write-key"},
    )


@pytest.fixture(autouse=True)
def _write_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "write-key")


def test_single_event_runs_pipeline_with_persisted_event_and_trigger_detail() -> None:
    clock = MutableClock(datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc))
    container = _container(clock)
    client = TestClient(create_app(container))

    response = _submit(client, "cpi-one", "us_cpi", clock.value, actual=0.5)

    assert response.status_code == 200  # type: ignore[attr-defined]
    with container.database.session() as session:
        run = RunRepository(session).latest()
        rows = RunRepository(session).list_runs(limit=10)
        event_log = EventLogRepository(session).list_by_type("event_triggered")
        assert run is not None
        inputs = RunRepository(session).get_inputs(str(run["run_id"]))
    assert len(rows) == 1
    assert run["trigger_type"] == "event"
    assert run["trigger_detail"] == {"event_id": "cpi-one", "debounced_events": 0}
    assert any(
        activation["rule_id"] == "cpi_hot_risk_assets_bearish"
        for asset in run["assets"]  # type: ignore[union-attr]
        for activation in asset["activated_rules"]
    )
    assert inputs is not None
    assert [event["event_id"] for event in inputs.raw_snapshots["events"]] == ["cpi-one"]
    assert event_log[-1].run_id == run["run_id"]


def test_events_inside_cooldown_are_aggregated_into_next_event_run() -> None:
    clock = MutableClock(datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc))
    container = _container(clock)
    client = TestClient(create_app(container))

    _submit(client, "event-1", "us_cpi", clock.value)
    clock.value += timedelta(minutes=10)
    _submit(client, "event-2", "fomc", clock.value)
    with container.database.session() as session:
        assert len(RunRepository(session).list_runs(limit=10)) == 1

    clock.value += timedelta(minutes=21)
    _submit(client, "event-3", "us_nfp", clock.value)

    with container.database.session() as session:
        runs = RunRepository(session).list_runs(limit=10)
        latest = RunRepository(session).latest()
        inputs = RunRepository(session).get_inputs(str(latest["run_id"]))  # type: ignore[index]
        debounced = EventLogRepository(session).list_by_type("event_debounced")
    assert len(runs) == 2
    assert latest is not None
    assert latest["trigger_detail"] == {"event_id": "event-2", "debounced_events": 1}
    assert inputs is not None
    assert [event["event_id"] for event in inputs.raw_snapshots["events"]] == [
        "event-2",
        "event-3",
    ]
    assert debounced[-1].payload["event_id"] == "event-2"


def test_cooldown_and_pending_events_survive_container_restart(tmp_path: Path) -> None:
    database_path = str(tmp_path / "event-restart.db")
    clock = MutableClock(datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc))
    first = _container(clock, database_path)
    first_client = TestClient(create_app(first))
    _submit(first_client, "event-1", "us_cpi", clock.value)
    clock.value += timedelta(minutes=10)
    _submit(first_client, "event-2", "fomc", clock.value)

    clock.value += timedelta(minutes=21)
    restarted = _container(clock, database_path)
    _submit(TestClient(create_app(restarted)), "event-3", "us_nfp", clock.value)

    with restarted.database.session() as session:
        runs = RunRepository(session).list_runs(limit=10)
        latest = RunRepository(session).latest()
    assert len(runs) == 2
    assert latest is not None
    assert latest["run_sequence"] == 2
    assert latest["trigger_detail"] == {"event_id": "event-2", "debounced_events": 1}


def test_duplicate_event_id_does_not_create_another_run() -> None:
    clock = MutableClock(datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc))
    container = _container(clock)
    client = TestClient(create_app(container))
    first = _submit(client, "same-event", "us_cpi", clock.value)
    clock.value += timedelta(hours=1)
    duplicate = _submit(client, "same-event", "us_cpi", clock.value, actual=9.0)

    assert first.json()["data"] == duplicate.json()["data"]  # type: ignore[attr-defined]
    with container.database.session() as session:
        assert len(RunRepository(session).list_runs(limit=10)) == 1
        assert len(EventLogRepository(session).list_by_type("event_triggered")) == 1


def test_failed_event_run_is_logged_and_remains_unpublished() -> None:
    clock = MutableClock(datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc))

    def failing_ingest(ctx: object) -> IngestBundle:
        raise RuntimeError("source down")

    container = build_container(
        REPO,
        env="dev",
        ingest_provider=failing_ingest,
        overrides={"anthropic": SequencedFake("anthropic")},
        clock=clock,
    )
    response = _submit(TestClient(create_app(container)), "failed-event", "us_cpi", clock.value)

    assert response.status_code == 200  # type: ignore[attr-defined]
    with container.database.session() as session:
        assert RunRepository(session).latest() is None
        failed = EventLogRepository(session).list_by_type("event_failed")
    assert failed[-1].payload["event_id"] == "failed-event"
    assert failed[-1].payload["error"] == "RuntimeError"
