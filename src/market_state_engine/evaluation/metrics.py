"""Evaluation metrics — aggregate operational metrics from stored Call Records + Event Log (F3).

Pure over stored data: latency, retries, provider success rate, degraded rate, replay success rate,
execution duration, token usage, and estimated cost. These are **operational-only** — a hard wall
keeps them out of every deterministic/model-quality path (ADR-007 D-7, pipelines.md §6). Provider
metrics never leak into evaluation of the model's market judgement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderMetrics:
    provider: str
    calls: int
    successes: int
    success_rate: float
    total_retries: int
    avg_latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost: float


@dataclass(frozen=True)
class MetricsSummary:
    total_calls: int
    success_rate: float
    timeout_rate: float
    error_rate: float
    avg_latency_ms: float
    total_retries: int
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost: float
    per_provider: dict[str, ProviderMetrics]


def _num(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def collect_call_metrics(call_records: Sequence[dict[str, object]]) -> MetricsSummary:
    """Aggregate a set of Call Record dicts (as returned by ``CallRecordRepository``)."""
    total = len(call_records)
    successes = [c for c in call_records if c.get("outcome") == "success"]
    timeouts = [c for c in call_records if c.get("outcome") == "timeout"]
    errors = [c for c in call_records if c.get("outcome") in ("error", "circuit_open")]
    latencies = [_num(c.get("latency_ms")) for c in successes]

    per_provider: dict[str, ProviderMetrics] = {}
    providers = sorted({str(c.get("provider")) for c in call_records})
    for name in providers:
        rows = [c for c in call_records if str(c.get("provider")) == name]
        ok = [c for c in rows if c.get("outcome") == "success"]
        prov_lat = [_num(c.get("latency_ms")) for c in ok]
        per_provider[name] = ProviderMetrics(
            provider=name,
            calls=len(rows),
            successes=len(ok),
            success_rate=(len(ok) / len(rows)) if rows else 0.0,
            total_retries=sum(_int(c.get("retries")) for c in rows),
            avg_latency_ms=(sum(prov_lat) / len(prov_lat)) if prov_lat else 0.0,
            input_tokens=sum(_int(c.get("input_tokens")) for c in ok),
            output_tokens=sum(_int(c.get("output_tokens")) for c in ok),
            estimated_cost=round(sum(_num(c.get("estimated_cost")) for c in ok), 6),
        )

    return MetricsSummary(
        total_calls=total,
        success_rate=(len(successes) / total) if total else 0.0,
        timeout_rate=(len(timeouts) / total) if total else 0.0,
        error_rate=(len(errors) / total) if total else 0.0,
        avg_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        total_retries=sum(_int(c.get("retries")) for c in call_records),
        total_input_tokens=sum(_int(c.get("input_tokens")) for c in successes),
        total_output_tokens=sum(_int(c.get("output_tokens")) for c in successes),
        total_estimated_cost=round(sum(_num(c.get("estimated_cost")) for c in successes), 6),
        per_provider=per_provider,
    )


@dataclass(frozen=True)
class RunRateMetrics:
    total_runs: int
    degraded_runs: int
    degraded_rate: float
    published_runs: int


def collect_run_rates(runs: Sequence[dict[str, object]]) -> RunRateMetrics:
    """Degraded/published rates over a set of stored MarketStateRun documents."""
    total = len(runs)
    degraded = sum(1 for r in runs if r.get("is_degraded") is True)
    published = total - degraded
    return RunRateMetrics(
        total_runs=total,
        degraded_runs=degraded,
        degraded_rate=(degraded / total) if total else 0.0,
        published_runs=published,
    )


@dataclass(frozen=True)
class ReplayRateMetrics:
    attempts: int
    successes: int
    replay_success_rate: float


def collect_replay_rate(results: Sequence[bool]) -> ReplayRateMetrics:
    attempts = len(results)
    successes = sum(1 for r in results if r)
    return ReplayRateMetrics(
        attempts=attempts,
        successes=successes,
        replay_success_rate=(successes / attempts) if attempts else 0.0,
    )
