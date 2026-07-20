"""Guardrails engine: run all deterministic checks and decide publish vs block. Pure.

Policy (cross-cutting.md §2): publish-with-flags for consistency/contradiction issues; block only
on a schema-invalid or critical-integrity failure. Range/schema validity is already guaranteed by
the Pydantic model construction; the CRITICAL findings here represent integrity violations that
should block publication.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_state_engine.core.enums import Severity
from market_state_engine.core.models import GuardrailFlag, MarketStateRun

from .checks import ALL_CHECKS, Finding


@dataclass(frozen=True)
class GuardrailResult:
    flags: list[GuardrailFlag]
    publish: bool


def _to_flag(finding: Finding) -> GuardrailFlag:
    return GuardrailFlag(
        code=finding.code,
        severity=finding.severity,
        detail=finding.detail,
        field=finding.field,
    )


def validate(run: MarketStateRun) -> GuardrailResult:
    findings: list[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(run))
    flags = [_to_flag(f) for f in findings]
    # Preserve any flags already present on the run (e.g. degraded_run, stale_price) — validate()
    # is called on a candidate that may already carry deterministic flags.
    existing = list(run.guardrail_flags)
    publish = not any(f.severity is Severity.CRITICAL for f in findings)
    return GuardrailResult(flags=existing + flags, publish=publish)
