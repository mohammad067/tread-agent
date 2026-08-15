"""Crypto Fear & Greed — Alternative.me public API (no key).

روند: GET api → value 0..100 → RawSnapshot برای global_snapshots['fear_greed']
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash
from market_state_engine.core.run_context import RunContext

_FNG_URL = "https://api.alternative.me/fng/?limit=1&format=json"


class FearGreedSource:
    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def fetch(self, ctx: RunContext) -> RawSnapshot:
        req = urllib.request.Request(
            _FNG_URL,
            headers={"Accept": "application/json", "User-Agent": "mse/0.1"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError("Fear&Greed API returned empty data")
        row = rows[0]
        value = int(row["value"])
        ts = int(row.get("timestamp") or 0)
        as_of = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if ts
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        payload = {
            "value": value,
            "as_of": as_of,
            "classification": row.get("value_classification"),
        }
        return RawSnapshot(
            source_id="alternative_me",
            symbol=None,
            payload=payload,
            as_of=as_of,
            is_stale=False,
            stale_reason=None,
            deviation_flags=[],
            content_hash=content_hash(payload),
        )
