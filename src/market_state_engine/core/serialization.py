"""Contract serialization helpers.

Some contract fields are required-and-nullable (must be emitted as ``null`` when unset) while
others are optional-non-nullable (must be omitted, never emitted as ``null``). ``prune_none``
drops ``None`` values except for a caller-provided set of keys that must be retained as ``null``.
"""

from __future__ import annotations

from collections.abc import Iterable


def prune_none(value: object, keep_null_keys: Iterable[str] = ()) -> object:
    keep = frozenset(keep_null_keys)
    if isinstance(value, dict):
        return {k: prune_none(v, keep) for k, v in value.items() if v is not None or k in keep}
    if isinstance(value, list):
        return [prune_none(v, keep) for v in value]
    return value
