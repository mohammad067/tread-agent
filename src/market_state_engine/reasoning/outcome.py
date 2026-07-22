"""Call outcome enumeration — the closed set recorded on every Call Record (call_record.v1.json)."""

from __future__ import annotations

from enum import Enum


class Outcome(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"
