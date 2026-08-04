"""ASGI entry point — composition root for uvicorn.

روند کار این فایل:
  1) مسیر ریشهٔ ریپو را پیدا می‌کند (جایی که config/ و rules/ هستند)
  2) از env می‌خواند: MSE_ENV، MSE_SQLITE_PATH، MSE_INGEST، MSE_LOG_LEVEL
  3) تصمیم می‌گیرد داده از mock بیاید یا از real_ingest_provider (CoinGecko و ...)
  4) کل گراف سرویس‌ها را با build_container می‌سازد (DB، قوانین، LLM gateway، scheduler)
  5) FastAPI app را می‌سازد تا endpointهای /v1/... در دسترس باشند

Uvicorn این ماژول را این‌طور لود می‌کند:
  python -m uvicorn market_state_engine.app.main:app
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from market_state_engine.api.app import create_app
from market_state_engine.app.container import Container, build_container
from market_state_engine.app.ingest import mock_ingest_provider
from market_state_engine.observability.logging import configure_logging

# parents[3]: .../app/main.py → app → market_state_engine → src → ریشهٔ ریپو
_ROOT = Path(__file__).resolve().parents[3]


def build_default_container() -> Container:
    """سیم‌کشی پیش‌فرض برای اجرای واقعی سرور (نه تست).

    روند:
      - env عملیاتی (dev/staging/prod)
      - مسیر فایل SQLite در dev
      - انتخاب provider ورودی:
          MSE_INGEST=real  → CoinGecko برای BTC/ETH (+ fallback mock)
          در غیر این صورت → mock_ingest_provider (دادهٔ ساختگی قبلی)
    """
    env = os.environ.get("MSE_ENV", "dev")
    sqlite_path = os.environ.get("MSE_SQLITE_PATH", str(_ROOT / "mse_dev.db"))

    # سوییچ ورودی واقعی / فیک — پیش‌فرض mock تا بدون اینترنت هم بالا بیاید
    ingest_mode = os.environ.get("MSE_INGEST", "mock").strip().lower()

    if ingest_mode == "real":
        # آداپترهای زنده در ingestion/real/provider.py
        from market_state_engine.ingestion.real.provider import real_ingest_provider

        ingest_provider = real_ingest_provider
    else:
        # همان دادهٔ سینوسی ثابت برای CI و توسعهٔ آفلاین
        ingest_provider = mock_ingest_provider

    return build_container(
        _ROOT,
        env=env,
        ingest_provider=ingest_provider,
        sqlite_path=sqlite_path,
    )


def create_default_app() -> FastAPI:
    """لاگ ساختاریافته را تنظیم می‌کند و app را به container وصل می‌کند."""
    configure_logging(os.environ.get("MSE_LOG_LEVEL", "INFO"))
    return create_app(build_default_container())


# آبجکت ASGI که uvicorn وارد می‌کند
app = create_default_app()