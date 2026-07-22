"""Static API-key auth (api-design.md §5). Keys from the environment only — never config or logs.

Two scopes: read (all GETs) and write (operational POSTs). A leaked read key cannot inject events.
Absent configured keys → the environment is treated as open for reads (dev), but writes always
require the write key. Validation is a header check in a dependency; no user accounts (§3).
"""

from __future__ import annotations

import os

READ_KEY_ENV = "MSE_API_READ_KEY"
WRITE_KEY_ENV = "MSE_API_WRITE_KEY"
API_KEY_HEADER = "x-api-key"


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def check_read(api_key: str | None) -> None:
    expected = os.environ.get(READ_KEY_ENV)
    if not expected:
        return  # no read key configured → reads are open (dev/CI)
    if api_key != expected:
        raise AuthError("unauthorized", "missing or invalid API key", 401)


def check_write(api_key: str | None) -> None:
    # --- TEMPORARY DIAGNOSTIC (remove after root cause proven) ---
    import sys as _sys

    print(
        "[DIAG check_write] "
        f"pid={os.getpid()} "
        f"file={__file__} "
        f"env_MSE_API_WRITE_KEY={os.environ.get(WRITE_KEY_ENV)!r} "
        f"id(os.environ)={id(os.environ)} "
        f"header_api_key={api_key!r} "
        f"env_keys_with_MSE={[k for k in os.environ if 'MSE' in k]}",
        file=_sys.stderr,
        flush=True,
    )
    # --- END TEMPORARY DIAGNOSTIC ---
    expected = os.environ.get(WRITE_KEY_ENV)
    if not expected:
        raise AuthError("unavailable", "write API key not configured", 503)
    read_key = os.environ.get(READ_KEY_ENV)
    if api_key == expected:
        return
    if read_key and api_key == read_key:
        raise AuthError("forbidden", "read key cannot be used on a write endpoint", 403)
    raise AuthError("unauthorized", "missing or invalid API key", 401)
