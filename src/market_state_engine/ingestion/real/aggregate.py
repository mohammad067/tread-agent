"""Merge multiple RawSnapshots for the same symbol into one (config-driven later).

Policy (MVP):
  - 0 snapshots → caller handles missing
  - 1 snapshot → return as-is
  - 2+ → prefer first non-stale; if values diverge beyond max_deviation_pct, flag deviation
    and still return the preferred payload (honest flag, no silent average unless asked)

Gate / CMC adapters will append into the same list; this function stays the single merge point.
"""

from __future__ import annotations

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash


def aggregate_snapshots(
    snapshots: list[RawSnapshot],
    *,
    max_deviation_pct: float = 2.0,
    prefer_source_id: str | None = None,
) -> RawSnapshot | None:
    if not snapshots:
        return None
    if len(snapshots) == 1:
        return snapshots[0]

    preferred = _pick(snapshots, prefer_source_id)
    pref_val = _value(preferred)
    flags: list[dict[str, object]] = list(preferred.deviation_flags)
    has_new_deviation = False

    for snap in snapshots:
        if snap is preferred:
            continue
        other = _value(snap)
        if pref_val is None or other is None or pref_val == 0:
            continue
        dev = abs(other - pref_val) / abs(pref_val) * 100.0
        if dev > max_deviation_pct:
            flags.append(
                {
                    "code": "cross_source_deviation",
                    "from_source": snap.source_id,
                    "vs_source": preferred.source_id,
                    "deviation_pct": round(dev, 6),
                }
            )
            has_new_deviation = True

    if not has_new_deviation:
        return preferred

    payload = dict(preferred.payload)
    return RawSnapshot(
        source_id=preferred.source_id,
        symbol=preferred.symbol,
        payload=payload,
        as_of=preferred.as_of,
        is_stale=preferred.is_stale,
        stale_reason=preferred.stale_reason,
        deviation_flags=flags,
        content_hash=content_hash(payload),
    )


def _pick(snapshots: list[RawSnapshot], prefer_source_id: str | None) -> RawSnapshot:
    if prefer_source_id:
        for s in snapshots:
            if s.source_id == prefer_source_id and not s.is_stale:
                return s
    for s in snapshots:
        if not s.is_stale:
            return s
    return snapshots[0]


def _value(snap: RawSnapshot) -> float | None:
    raw = snap.payload.get("value")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None
