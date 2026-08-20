"""API validation (M5): every endpoint from the frozen catalog + contract-shaped envelope/errors."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from market_state_engine.api.app import create_app
from market_state_engine.persistence.repositories import MacroEventRepository

from ._harness import build_degraded_container, build_full_container


@pytest.fixture
def client_full() -> tuple[TestClient, str]:
    c = build_full_container()
    summary = c.scheduler.run_manual()
    return TestClient(create_app(c)), summary.run_id


def test_state_latest_returns_envelope(client_full: tuple[TestClient, str]) -> None:
    client, _ = client_full
    resp = client.get("/v1/state/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and "meta" in body
    meta = body["meta"]
    assert meta["api_version"] == "v1"
    assert meta["schema_version"] == "1.0.0"
    assert "disclaimer" in meta
    assert "is_degraded" in meta


def test_run_by_id(client_full: tuple[TestClient, str]) -> None:
    client, run_id = client_full
    resp = client.get(f"/v1/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["run_id"] == run_id


def test_run_by_id_unknown_is_404(client_full: tuple[TestClient, str]) -> None:
    client, _ = client_full
    resp = client.get("/v1/runs/DOES_NOT_EXIST")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert "correlation_id" in resp.json()["error"]


def test_runs_list_paginated(client_full: tuple[TestClient, str]) -> None:
    client, _ = client_full
    resp = client.get("/v1/runs?limit=5")
    assert resp.status_code == 200
    assert "pagination" in resp.json()["meta"]
    assert isinstance(resp.json()["data"], list)


def test_run_inputs(client_full: tuple[TestClient, str]) -> None:
    client, run_id = client_full
    resp = client.get(f"/v1/runs/{run_id}/inputs")
    assert resp.status_code == 200
    assert resp.json()["data"]["run_id"] == run_id
    assert "snapshot_hash" in resp.json()["data"]


def test_run_calls(client_full: tuple[TestClient, str]) -> None:
    client, run_id = client_full
    resp = client.get(f"/v1/runs/{run_id}/calls")
    assert resp.status_code == 200
    calls = resp.json()["data"]
    assert len(calls) == 2
    assert {c["llm_job"] for c in calls} == {"sentiment", "synthesis"}


def test_meta_versions(client_full: tuple[TestClient, str]) -> None:
    client, _ = client_full
    resp = client.get("/v1/meta/versions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["schema"] == "1.0.0"
    assert "rulebook" in data and "pipeline" in data


def test_marketstaterun_response_validates_against_schema(
    client_full: tuple[TestClient, str], make_validator: Any
) -> None:
    client, _ = client_full
    run = client.get("/v1/state/latest").json()["data"]
    validator = make_validator("market_state_run.v1.0.0.json")
    errors = list(validator.iter_errors(run))
    assert not errors, [e.message for e in errors]


# --- Degraded run over the API -------------------------------------------------------
def test_degraded_run_returns_200_with_flag() -> None:
    c = build_degraded_container()
    c.scheduler.run_manual()
    client = TestClient(create_app(c))
    resp = client.get("/v1/state/latest")
    assert resp.status_code == 200  # provider outage is never an API error (ADR-011)
    assert resp.json()["meta"]["is_degraded"] is True


# --- Observability -------------------------------------------------------------------
def test_health_liveness_readiness_metrics() -> None:
    c = build_full_container()
    c.scheduler.run_manual()
    client = TestClient(create_app(c))
    assert client.get("/v1/health").status_code == 200
    assert client.get("/health/live").json()["status"] == "alive"
    assert client.get("/health/ready").json()["status"] == "ready"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "event_log_entries" in metrics.text


# --- Auth / operational writes -------------------------------------------------------
def test_write_endpoint_without_key_is_503() -> None:
    c = build_full_container()
    client = TestClient(create_app(c))
    resp = client.post("/v1/events", json={"event_type": "us_cpi", "consensus": 0.3, "actual": 0.4})
    assert resp.status_code == 503  # write key not configured


def test_write_endpoint_with_key_accepts_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "secret-write")
    c = build_full_container()
    client = TestClient(create_app(c))
    resp = client.post(
        "/v1/events",
        json={
            "event_type": "us_cpi",
            "event_id": "e1",
            "scheduled_at": "2026-08-20T12:30:00Z",
            "consensus": 0.3,
            "actual": 0.45,
        },
        headers={"x-api-key": "secret-write"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["accepted"] is True
    assert data["surprise"] == pytest.approx(0.15)  # computed server-side
    assert set(data) == {"event_id", "accepted", "surprise"}
    with c.database.session() as session:
        stored = MacroEventRepository(session).get("e1")
    assert stored is not None
    assert stored.event_type == "us_cpi"
    assert stored.surprise == pytest.approx(0.15)
    assert stored.raw["actual"] == 0.45


def test_duplicate_macro_event_is_idempotent_and_does_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "write-key")
    c = build_full_container()
    client = TestClient(create_app(c))
    original = {
        "event_id": "same-event",
        "event_type": "us_cpi",
        "scheduled_at": "2026-08-20T12:30:00Z",
        "consensus": 0.3,
        "actual": 0.4,
    }
    first = client.post("/v1/events", json=original, headers={"x-api-key": "write-key"})
    duplicate = client.post(
        "/v1/events",
        json={**original, "actual": 9.0},
        headers={"x-api-key": "write-key"},
    )

    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["data"] == first.json()["data"]
    with c.database.session() as session:
        events = MacroEventRepository(session).list_events()
        stored = MacroEventRepository(session).get("same-event")
    assert [event.event_id for event in events] == ["same-event"]
    assert stored is not None and stored.actual == 0.4


@pytest.mark.parametrize(
    "payload",
    [
        {
            "event_id": "bad-type",
            "event_type": "unknown",
            "scheduled_at": "2026-08-20T12:30:00Z",
            "consensus": 0.3,
        },
        {
            "event_type": "us_cpi",
            "scheduled_at": "2026-08-20T12:30:00Z",
            "consensus": 0.3,
        },
        {
            "event_id": "client-surprise",
            "event_type": "us_cpi",
            "scheduled_at": "2026-08-20T12:30:00Z",
            "consensus": 0.3,
            "actual": 0.4,
            "surprise": 99.0,
        },
    ],
)
def test_invalid_macro_event_is_rejected(
    payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "write-key")
    c = build_full_container()
    client = TestClient(create_app(c))

    response = client.post("/v1/events", json=payload, headers={"x-api-key": "write-key"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    with c.database.session() as session:
        assert MacroEventRepository(session).list_events() == []


def test_read_key_rejected_on_write_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_READ_KEY", "read-only")
    monkeypatch.setenv("MSE_API_WRITE_KEY", "write-key")
    c = build_full_container()
    client = TestClient(create_app(c))
    resp = client.post(
        "/v1/events",
        json={"event_type": "us_cpi", "consensus": 0.3, "actual": 0.4},
        headers={"x-api-key": "read-only"},
    )
    assert resp.status_code == 403


def test_manual_trigger_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "write-key")
    c = build_full_container()
    client = TestClient(create_app(c))
    resp = client.post(
        "/v1/runs:trigger", json={"reason": "test"}, headers={"x-api-key": "write-key"}
    )
    assert resp.status_code == 200
    run_id = resp.json()["data"]["run_id"]
    latest = client.get("/v1/state/latest")
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == run_id
