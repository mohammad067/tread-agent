"""ASGI entry point — build the default container and the FastAPI app for a real server.

This is the composition root's runtime entry: it wires the default container (config-driven, from
the project root and ``MSE_ENV`` — default ``dev``) with the mock ingestion provider, then hands it
to the API factory ``create_app``. Uvicorn loads ``market_state_engine.app.main:app``.

The factory pattern is preserved: tests still build their own container and call ``create_app`` with
it; this module only provides the *default* wiring for `uvicorn`/production startup.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from market_state_engine.api.app import create_app
from market_state_engine.app.container import Container, build_container
from market_state_engine.app.ingest import mock_ingest_provider
from market_state_engine.observability.logging import configure_logging

# Project root = repo root (config/, rules/, prompts/, schemas/ live here — master-prompt §10).
_ROOT = Path(__file__).resolve().parents[3]


def build_default_container() -> Container:
    """Wire the default container from configuration (no hardcoded values beyond the seam)."""
    env = os.environ.get("MSE_ENV", "dev")
    sqlite_path = os.environ.get("MSE_SQLITE_PATH", str(_ROOT / "mse_dev.db"))
    return build_container(
        _ROOT,
        env=env,
        ingest_provider=mock_ingest_provider,
        sqlite_path=sqlite_path,
    )


def create_default_app() -> FastAPI:
    configure_logging(os.environ.get("MSE_LOG_LEVEL", "INFO"))
    return create_app(build_default_container())


# The ASGI application object uvicorn imports: `uvicorn market_state_engine.app.main:app`.
app = create_default_app()
