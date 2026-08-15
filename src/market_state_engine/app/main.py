"""ASGI entry point — composition root for uvicorn.

روند کار این فایل:
  1) .env را لود می‌کند (GOLD_API_KEY، MSE_*، کلید LLM و ...)
  2) مسیر ریشهٔ ریپو را پیدا می‌کند
  3) از env: MSE_ENV، MSE_SQLITE_PATH، MSE_INGEST، MSE_LOG_LEVEL
  4) mock یا real_ingest_provider
  5) build_container + FastAPI app
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from market_state_engine.api.app import create_app
from market_state_engine.app.container import Container, build_container
from market_state_engine.app.ingest import mock_ingest_provider
from market_state_engine.observability.logging import configure_logging

# خواندن فایل .env از ریشهٔ پروژه (اگر python-dotenv نصب باشد)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# parents[3]: .../app/main.py → app → market_state_engine → src → ریشهٔ ریپو
_ROOT = Path(__file__).resolve().parents[3]


def build_default_container() -> Container:
    env = os.environ.get("MSE_ENV", "dev")
    sqlite_path = os.environ.get("MSE_SQLITE_PATH", str(_ROOT / "mse_dev.db"))

    ingest_mode = os.environ.get("MSE_INGEST", "mock").strip().lower()

    if ingest_mode == "real":
        from market_state_engine.ingestion.real.provider import real_ingest_provider

        ingest_provider = real_ingest_provider
    else:
        ingest_provider = mock_ingest_provider

    return build_container(
        _ROOT,
        env=env,
        ingest_provider=ingest_provider,
        sqlite_path=sqlite_path,
    )


def create_default_app() -> FastAPI:
    configure_logging(os.environ.get("MSE_LOG_LEVEL", "INFO"))
    return create_app(build_default_container())


app = create_default_app()
