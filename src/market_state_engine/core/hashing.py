"""Deterministic content hashing for replay integrity.

A snapshot/prompt hash must be stable across processes and runs, so we serialize with sorted keys
and a fixed separator before hashing. Pure — no I/O.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def content_hash(payload: Any) -> str:
    """Return a stable SHA-256 hex digest of a JSON-serializable payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
