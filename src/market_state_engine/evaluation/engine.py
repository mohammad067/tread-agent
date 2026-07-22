"""Evaluation Engine — correctness checks over stored runs and replays (module-catalog F3).

Produces a pass/fail ``CheckResult`` for each evaluation dimension the milestone requires:
  - replay correctness            — the run reproduces byte-identically via ReplayProvider
  - provider correctness          — every Call Record has a coherent outcome/response shape
  - deterministic consistency     — recomputing twice yields identical deterministic fields
  - schema validity               — the stored MarketStateRun validates against the frozen schema
  - api/contract validity         — the run carries the required contract fields + envelope shape
  - degraded execution correctness— degraded runs honour ADR-011 (honest absence + flag)
  - prompt consistency            — identical rendered prompts hash identically (replay-stable)

Pure over stored data (schema files + Event Log). No market number is computed here; no live
provider is contacted. Reuses ``ReplayHarness`` and the frozen schema registry.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from market_state_engine.evaluation.replay_harness import ReplayResult
from market_state_engine.evaluation.schema_registry import market_state_run_validator


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationSummary:
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)


# --- individual checks ---------------------------------------------------------------
def check_replay_correctness(replay: ReplayResult) -> CheckResult:
    """Verify the frozen replay guarantee: the deterministic core reproduces byte-identically.

    ``deterministic_match`` is the sentiment-independent core (regime/trend/risk/rules) — the frozen
    guarantee (database.md §5, ADR-011 DR-4). Call-record replay is additionally required when the
    LLM leg was reproducible (``full_deterministic_match``); a run whose sentiment used news that
    isn't persisted still satisfies the core guarantee.
    """
    failures: list[str] = []
    if not replay.deterministic_match:
        failures.append(
            f"deterministic core diverged: "
            f"{replay.stored_core_fingerprint} != {replay.replayed_core_fingerprint}"
        )
    if replay.full_deterministic_match and not replay.call_records_match:
        failures.extend(
            f"{d.field}: {d.recorded} != {d.replayed}" for d in replay.call_verification.diffs
        )
    return CheckResult("replay_correctness", not failures, "core reproduced", failures)


def check_provider_correctness(call_records: Sequence[dict[str, object]]) -> CheckResult:
    failures: list[str] = []
    valid_outcomes = {"success", "timeout", "error", "circuit_open"}
    for i, c in enumerate(call_records):
        outcome = c.get("outcome")
        if outcome not in valid_outcomes:
            failures.append(f"[{i}] invalid outcome {outcome!r}")
        if outcome == "success" and c.get("response") is None:
            failures.append(f"[{i}] success with null response")
        if outcome != "success" and c.get("response") is not None:
            failures.append(f"[{i}] non-success with non-null response")
    return CheckResult(
        "provider_correctness", not failures, f"{len(call_records)} call records", failures
    )


def check_deterministic_consistency(first_fp: str, second_fp: str) -> CheckResult:
    ok = first_fp == second_fp
    return CheckResult(
        "deterministic_consistency",
        ok,
        "recompute-twice identical" if ok else f"{first_fp} != {second_fp}",
        [] if ok else ["deterministic fields changed across two recomputations"],
    )


def check_schema_validity(run: dict[str, object], schemas_dir: Path) -> CheckResult:
    validator = market_state_run_validator(schemas_dir)
    errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(run)]
    return CheckResult("schema_validity", not errors, "market_state_run.v1.0.0", errors)


_CONTRACT_FIELDS = (
    "schema_version",
    "run_id",
    "run_sequence",
    "trigger_type",
    "generated_at",
    "is_degraded",
    "versions",
    "regime",
    "assets",
    "global",
    "guardrail_flags",
    "disclaimer",
)


def check_contract_validity(run: dict[str, object]) -> CheckResult:
    missing = [f for f in _CONTRACT_FIELDS if f not in run]
    return CheckResult(
        "contract_validity",
        not missing,
        "all contract fields present",
        [f"missing field: {f}" for f in missing],
    )


def check_degraded_correctness(run: dict[str, object]) -> CheckResult:
    """A degraded run must show honest absence + the degraded_run flag (ADR-011)."""
    if run.get("is_degraded") is not True:
        return CheckResult("degraded_correctness", True, "run is not degraded (n/a)")
    failures: list[str] = []
    assets = run.get("assets")
    asset_list = assets if isinstance(assets, list) else []
    for asset in asset_list:
        a = dict(asset) if isinstance(asset, dict) else {}
        raw_scores = a.get("scores")
        scores = raw_scores if isinstance(raw_scores, dict) else {}
        if scores.get("sentiment") is not None:
            failures.append(f"{a.get('symbol')}: sentiment present on degraded run")
        if "human_summary_fa" in a:
            failures.append(f"{a.get('symbol')}: human_summary_fa present on degraded run")
    flags = run.get("guardrail_flags")
    flag_list = flags if isinstance(flags, list) else []
    codes = {f.get("code") for f in flag_list if isinstance(f, dict)}
    if "degraded_run" not in codes:
        failures.append("missing degraded_run guardrail flag")
    return CheckResult("degraded_correctness", not failures, "honest absence + flag", failures)


def check_prompt_consistency(call_records: Sequence[dict[str, object]]) -> CheckResult:
    """The same rendered prompt must always carry the same prompt_hash (replay-stable, #4)."""
    by_hash: dict[str, str] = {}
    failures: list[str] = []
    for c in call_records:
        rendered = c.get("rendered_prompt")
        prompt_hash = c.get("prompt_hash")
        if not isinstance(rendered, str) or not isinstance(prompt_hash, str):
            continue
        if rendered in by_hash and by_hash[rendered] != prompt_hash:
            failures.append(f"same prompt, differing hash: {by_hash[rendered]} != {prompt_hash}")
        by_hash[rendered] = prompt_hash
    return CheckResult("prompt_consistency", not failures, "stable prompt hashing", failures)
