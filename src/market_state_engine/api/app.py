"""FastAPI application factory — the complete API surface (api-design.md §2 endpoint catalog).

Endpoints exactly as designed (no redesign): read GETs for state/runs/inputs/calls/meta, two guarded
operational POSTs (events, runs:trigger), plus observability (health/readiness/liveness/metrics).
Every read is a persisted-document lookup — no computation on the request path. The app receives a
fully-wired ``Container`` (DI); it holds no business logic and constructs no market numbers.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from market_state_engine.app.container import Container
from market_state_engine.core.enums import EventType as MacroEventType
from market_state_engine.persistence.repositories import (
    CallRecordRepository,
    EventLogRepository,
    RunRepository,
)
from market_state_engine.pipeline.scheduler import OverlapError

from .envelope import envelope, error_body
from .security import API_KEY_HEADER, AuthError, check_read, check_write

_MACRO_EVENT_TYPES = {e.value for e in MacroEventType}


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="Market State Engine API", version="v1")

    def _corr(request: Request) -> str:
        return request.headers.get("x-correlation-id", str(uuid.uuid4()))

    @app.exception_handler(AuthError)
    async def _auth_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.code, exc.message, _corr(request)),
        )

    # --- Reads (key-gated) -------------------------------------------------------------
    @app.get("/v1/state/latest")
    def state_latest(
        request: Request, x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)
    ) -> Any:
        check_read(x_api_key)
        with container.database.session() as session:
            run = RunRepository(session).latest()
        if run is None:
            return _not_found(request, "no runs available")
        return envelope(run, is_degraded=bool(run.get("is_degraded")))

    @app.get("/v1/runs/{run_id}")
    def run_by_id(
        run_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_read(x_api_key)
        with container.database.session() as session:
            run = RunRepository(session).get(run_id)
        if run is None:
            return _not_found(request, f"run {run_id} not found")
        return envelope(run, is_degraded=bool(run.get("is_degraded")))

    @app.get("/v1/runs")
    def runs_range(
        request: Request,
        trigger_type: str | None = None,
        limit: int = 50,
        cursor: int = 0,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_read(x_api_key)
        limit = max(1, min(limit, 200))
        with container.database.session() as session:
            runs = RunRepository(session).list_runs(
                trigger_type=trigger_type, limit=limit, offset=cursor
            )
        next_cursor = cursor + limit if len(runs) == limit else None
        return envelope(runs, pagination={"next_cursor": next_cursor, "limit": limit})

    @app.get("/v1/runs/{run_id}/inputs")
    def run_inputs(
        run_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_read(x_api_key)
        with container.database.session() as session:
            row = RunRepository(session).get_inputs(run_id)
            data = (
                None
                if row is None
                else {
                    "run_id": row.run_id,
                    "raw_snapshots": row.raw_snapshots,
                    "snapshot_hash": row.snapshot_hash,
                    "data_gaps": row.data_gaps,
                    "deviation_flags": row.deviation_flags,
                    "ingested_at": row.ingested_at,
                }
            )
        if data is None:
            return _not_found(request, f"inputs for run {run_id} not found")
        return envelope(data)

    @app.get("/v1/runs/{run_id}/calls")
    def run_calls(
        run_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_read(x_api_key)
        with container.database.session() as session:
            calls = CallRecordRepository(session).list_for_run(run_id)
        return envelope(calls)

    @app.get("/v1/meta/versions")
    def meta_versions(
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_read(x_api_key)
        versions = {
            "schema": "1.0.0",
            "pipeline": container.pipeline_version,
            "rulebook": container.rulebook_version,
            "mhi_weights": container.config.mhi_weights.version,
            "source_quality": container.config.source_quality.version,
            "half_lives": container.config.half_lives.version,
        }
        return envelope(versions)

    # --- Operational writes (write-key-gated) ------------------------------------------
    @app.post("/v1/events")
    def submit_event(
        body: dict[str, Any],
        request: Request,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_write(x_api_key)
        event_type = body.get("event_type")
        if event_type not in _MACRO_EVENT_TYPES:
            return _invalid(request, "unknown or missing event_type")
        # Surprise is computed server-side, never trusted from the client (api-db-fixtures A.3).
        consensus = body.get("consensus")
        actual = body.get("actual")
        surprise = (
            float(actual) - float(consensus)
            if isinstance(actual, (int, float)) and isinstance(consensus, (int, float))
            else None
        )
        return envelope({"event_id": body.get("event_id"), "accepted": True, "surprise": surprise})

    @app.post("/v1/runs:trigger")
    def trigger_run(
        request: Request,
        body: dict[str, Any] | None = None,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> Any:
        check_write(x_api_key)
        try:
            summary = container.scheduler.run_manual()
        except OverlapError:
            return JSONResponse(
                status_code=409,
                content=error_body("conflict", "a run is already in progress", _corr(request)),
            )
        return envelope({"run_id": summary.run_id, "status": summary.status})

    # --- Observability (open) ----------------------------------------------------------
    @app.get("/v1/health")
    def health() -> Any:
        return envelope({"status": "ok"})

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def readiness() -> Response:
        try:
            with container.database.session() as session:
                RunRepository(session).latest()
            return JSONResponse({"status": "ready"})
        except Exception:  # dependency (DB) down → 503, never a market error
            return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/metrics")
    def metrics() -> Response:
        snapshot = container.metrics.snapshot()
        with container.database.session() as session:
            snapshot["event_log_entries"] = float(EventLogRepository(session).count())
        container_metrics = container.metrics
        for name, value in snapshot.items():
            container_metrics.set_gauge(name, value)
        return PlainTextResponse(container.metrics.render_prometheus())

    def _not_found(request: Request, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=404, content=error_body("not_found", message, _corr(request))
        )

    def _invalid(request: Request, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=error_body("invalid_request", message, _corr(request))
        )

    return app


def __getattr__(name: str) -> object:
    """Expose a module-level ``app`` ASGI object lazily for ``uvicorn ...api.app:app``.

    Building it eagerly would wire the whole container on every ``from .app import create_app``
    (e.g. in tests). PEP 562 lets us construct the default app only when ``app`` is actually
    accessed, keeping the factory pattern intact. The canonical entry point is
    ``market_state_engine.app.main:app``; this delegates to it.
    """
    if name == "app":
        from market_state_engine.app.main import app as default_app

        return default_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
