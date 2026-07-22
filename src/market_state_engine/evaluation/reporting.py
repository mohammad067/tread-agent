"""Reporting — assemble the Milestone 6 reports from component outputs (module-catalog F3).

Pure formatting: turns the typed results from ReplayHarness / Evaluation Engine / Metrics /
Ablation / Validation into JSON-serializable report documents. Five reports:
  - replay report                — per-run replay equivalence + aggregate replay-success rate.
  - evaluation report            — the correctness checks (replay/provider/determinism/schema/…).
  - provider report              — per-provider operational metrics (success rate, latency, tokens,
                                   cost) — operational only (ADR-007 D-7).
  - degradation report           — degraded-run rate + honesty check.
  - production validation report — the production-readiness verdict.

No I/O and no market computation here; callers persist/print the returned dicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict

from market_state_engine.evaluation.engine import EvaluationSummary
from market_state_engine.evaluation.metrics import (
    MetricsSummary,
    RunRateMetrics,
)
from market_state_engine.evaluation.replay_harness import ReplayResult
from market_state_engine.evaluation.validation import ValidationReport


def replay_report(results: Sequence[ReplayResult]) -> dict[str, object]:
    attempts = len(results)
    successes = sum(1 for r in results if r.ok)
    return {
        "report": "replay",
        "attempts": attempts,
        "successes": successes,
        "replay_success_rate": (successes / attempts) if attempts else 0.0,
        "runs": [
            {
                "run_id": r.run_id,
                "deterministic_match": r.deterministic_match,
                "full_deterministic_match": r.full_deterministic_match,
                "call_records_match": r.call_records_match,
                "reproduced_is_degraded": r.reproduced_is_degraded,
            }
            for r in results
        ],
    }


def evaluation_report(summary: EvaluationSummary) -> dict[str, object]:
    return {
        "report": "evaluation",
        "passed": summary.passed,
        "pass_count": summary.pass_count,
        "total_checks": len(summary.checks),
        "checks": [asdict(c) for c in summary.checks],
    }


def provider_report(metrics: MetricsSummary) -> dict[str, object]:
    return {
        "report": "provider",
        "total_calls": metrics.total_calls,
        "success_rate": metrics.success_rate,
        "timeout_rate": metrics.timeout_rate,
        "error_rate": metrics.error_rate,
        "avg_latency_ms": metrics.avg_latency_ms,
        "total_retries": metrics.total_retries,
        "total_input_tokens": metrics.total_input_tokens,
        "total_output_tokens": metrics.total_output_tokens,
        "total_estimated_cost": metrics.total_estimated_cost,
        "per_provider": {name: asdict(pm) for name, pm in metrics.per_provider.items()},
    }


def degradation_report(rates: RunRateMetrics, honesty_ok: bool) -> dict[str, object]:
    return {
        "report": "degradation",
        "total_runs": rates.total_runs,
        "degraded_runs": rates.degraded_runs,
        "degraded_rate": rates.degraded_rate,
        "published_runs": rates.published_runs,
        "honest_absence_verified": honesty_ok,
    }


def production_validation_report(report: ValidationReport) -> dict[str, object]:
    return {
        "report": "production_validation",
        "production_ready": report.production_ready,
        "checks": [asdict(c) for c in report.checks],
    }
