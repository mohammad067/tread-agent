"""Deterministic multi-source spot aggregation for BTC and ETH (ADR-009).

Only structurally valid, fresh observations participate. The aggregate is a
median and never silently selects a preferred venue. Historical indicator
series remain separate from this spot-price snapshot.
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from market_state_engine.core.dtos import RawSnapshot
from market_state_engine.core.hashing import content_hash

_POLICY_VERSION = "adr-009/2"


def aggregate_snapshots(
    snapshots: list[RawSnapshot],
    *,
    expected_symbol: str,
    min_sources: int,
    configured_source_ids: tuple[str, ...],
    max_deviation_pct: float,
    now: datetime,
    staleness_threshold_minutes: int,
) -> RawSnapshot | None:
    """Return an audited median snapshot, or ``None`` when policy is not met."""
    valid = _valid_observations(
        snapshots,
        expected_symbol=expected_symbol,
        configured_source_ids=configured_source_ids,
        now=now,
        staleness_threshold_minutes=staleness_threshold_minutes,
    )
    if len(valid) < min_sources:
        return None

    values = [_value(snapshot) for snapshot in valid]
    aggregate_value = float(median(values))

    # A two-source fallback is usable only when the pair agrees within the
    # configured threshold. Three-source median remains robust to one outlier.
    if len(valid) == 2 and _pairwise_deviation(values[0], values[1]) > max_deviation_pct:
        return None

    flags = _source_flags(valid)
    if len(valid) < len(configured_source_ids):
        flags.append(
            {
                "code": "reduced_source_count",
                "configured_sources": len(configured_source_ids),
                "valid_sources": len(valid),
            }
        )

    observations: list[dict[str, object]] = []
    for snapshot, value in zip(valid, values, strict=True):
        deviation = _deviation_from(value, aggregate_value)
        observation: dict[str, object] = {
            "source_id": snapshot.source_id,
            "value": value,
            "as_of": snapshot.as_of,
            "content_hash": snapshot.content_hash,
            "source_quote_currency": snapshot.payload["source_quote_currency"],
            "deviation_pct": round(deviation, 6),
        }
        source_pair = snapshot.payload.get("source_pair")
        if isinstance(source_pair, str):
            observation["source_pair"] = source_pair
        observations.append(observation)
        if deviation > max_deviation_pct:
            flags.append(
                {
                    "code": "cross_source_deviation",
                    "from_source": snapshot.source_id,
                    "vs_source": "crypto_median",
                    "deviation_pct": round(deviation, 6),
                }
            )

    latest = max(valid, key=lambda snapshot: (_parse_as_of(snapshot.as_of), snapshot.source_id))
    payload: dict[str, object] = {
        "as_of": latest.as_of,
        "value": aggregate_value,
        "currency": "USD",
        "aggregation_policy_version": _POLICY_VERSION,
        "venue_aggregation": f"median_{len(valid)}",
        "source_observations": observations,
    }
    return RawSnapshot(
        source_id="crypto_median",
        symbol=expected_symbol,
        payload=payload,
        as_of=latest.as_of,
        is_stale=False,
        stale_reason=None,
        deviation_flags=flags,
        content_hash=content_hash(payload),
    )


def _valid_observations(
    snapshots: list[RawSnapshot],
    *,
    expected_symbol: str,
    configured_source_ids: tuple[str, ...],
    now: datetime,
    staleness_threshold_minutes: int,
) -> list[RawSnapshot]:
    duplicate_ids = {
        source_id
        for source_id in {snapshot.source_id for snapshot in snapshots}
        if sum(snapshot.source_id == source_id for snapshot in snapshots) > 1
    }
    valid: list[RawSnapshot] = []
    for snapshot in snapshots:
        if snapshot.source_id not in configured_source_ids:
            continue
        if snapshot.source_id in duplicate_ids:
            continue
        if snapshot.symbol != expected_symbol or snapshot.is_stale:
            continue
        if _optional_value(snapshot) is None:
            continue
        if snapshot.payload.get("currency") != "USD":
            continue
        quote = snapshot.payload.get("source_quote_currency")
        if not isinstance(quote, str) or not quote:
            continue
        try:
            observed_at = _parse_as_of(snapshot.as_of)
        except ValueError:
            continue
        age_seconds = (now - observed_at).total_seconds()
        if age_seconds < 0 or age_seconds > staleness_threshold_minutes * 60:
            continue
        valid.append(snapshot)
    return sorted(valid, key=lambda snapshot: snapshot.source_id)


def _source_flags(snapshots: list[RawSnapshot]) -> list[dict[str, object]]:
    flags: list[dict[str, object]] = []
    for snapshot in snapshots:
        flags.extend(dict(flag) for flag in snapshot.deviation_flags)
    return flags


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("snapshot timestamp must include a timezone")
    return parsed


def _optional_value(snapshot: RawSnapshot) -> float | None:
    raw = snapshot.payload.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) and value > 0 else None


def _value(snapshot: RawSnapshot) -> float:
    value = _optional_value(snapshot)
    if value is None:  # pragma: no cover - callers pass validated observations
        raise ValueError("invalid snapshot value")
    return value


def _deviation_from(value: float, reference: float) -> float:
    return abs(value - reference) / reference * 100.0


def _pairwise_deviation(left: float, right: float) -> float:
    midpoint = (left + right) / 2.0
    return abs(left - right) / midpoint * 100.0
