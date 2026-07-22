"""Response envelope + error contract (api-design.md §3, §7). Presentation shaping only."""

from __future__ import annotations

from typing import Any

_DISCLAIMER = "Market observation only. Not investment advice."
_API_VERSION = "v1"
_SCHEMA_VERSION = "1.0.0"


def envelope(
    data: Any,
    *,
    next_scheduled_run: str | None = None,
    is_degraded: bool | None = None,
    pagination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "api_version": _API_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "next_scheduled_run": next_scheduled_run,
        "disclaimer": _DISCLAIMER,
    }
    if is_degraded is not None:
        meta["is_degraded"] = is_degraded
    if pagination is not None:
        meta["pagination"] = pagination
    return {"data": data, "meta": meta}


def error_body(code: str, message: str, correlation_id: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "correlation_id": correlation_id}
    }
    if details is not None:
        body["error"]["details"] = details
    return body
