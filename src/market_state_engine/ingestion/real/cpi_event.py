"""Load US CPI MacroEvent from config (data separated from provider code).

روند:
  config/events/us_cpi_latest.yaml → MacroEvent
  اگر فایل نباشد یا ناقص باشد → None (run بدون این event ادامه می‌یابد)
بعداً می‌توان همین تابع را به API تقویم اقتصادی وصل کرد بدون تغییر provider.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from market_state_engine.core.dtos import MacroEvent
from market_state_engine.core.enums import EventType

_log = logging.getLogger("ingestion.real.cpi")

_DEFAULT_REL = Path("config") / "events" / "us_cpi_latest.yaml"


def load_us_cpi_event(project_root: Path, rel: Path = _DEFAULT_REL) -> MacroEvent | None:
    path = project_root / rel
    if not path.is_file():
        _log.warning("cpi_yaml_missing path=%s", path)
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log.warning("cpi_yaml_read_fail path=%s err=%s", path, exc)
        return None

    try:
        event_id = str(raw["event_id"])
        scheduled_at = str(raw["scheduled_at"])
        consensus = float(raw["consensus"])
        actual_raw = raw.get("actual", None)
        actual = float(actual_raw) if actual_raw is not None else None
        event_type = EventType.US_CPI
    except (KeyError, TypeError, ValueError) as exc:
        _log.warning("cpi_yaml_invalid path=%s err=%s", path, exc)
        return None

    return MacroEvent(
        event_id=event_id,
        event_type=event_type,
        scheduled_at=scheduled_at,
        consensus=consensus,
        actual=actual,
    )
