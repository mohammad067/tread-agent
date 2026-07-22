"""Replay loading, execution wiring, and verification for LLM interactions (frozen invariant #6).

A recorded run's Call Records are the lossless replay unit (ADR-004 / ADR-007 D-6). This module:
  - **loads** Call Records from the Event Log's serialized form (``load_call_records``),
  - **wires** them into ``ReplayProvider`` adapters, one per recorded provider
    (``build_replay_adapters``) — drop-in replacements the Gateway drives exactly like live ones,
  - **verifies** a fresh run's records reproduce the recorded ones byte-identically
    (``verify_replay`` → ``ReplayVerification``), comparing prompt/response hashes and outcomes.

Verification compares the replay-critical fields (prompt hash, response hash, outcome, provider,
model) — not wall-clock latency, which is environmental. A mismatch is reported, never silently
tolerated. Pure: no network; the Gateway under replay never reaches a vendor.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.replay import ReplayProvider
from .models import CallRecord


def load_call_records(records: Iterable[Mapping[str, object]]) -> list[CallRecord]:
    """Parse serialized Call Records (e.g. from the Event Log) into typed models."""
    return [CallRecord.model_validate(r) for r in records]


def load_call_records_json(path: Path) -> list[CallRecord]:
    """Load Call Records from a JSON file holding a list of record objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of call records")
    return load_call_records(data)


def build_replay_adapters(records: Iterable[CallRecord]) -> dict[str, ReplayProvider]:
    """Build one ``ReplayProvider`` per distinct provider in the recorded set."""
    records = list(records)
    providers = sorted({r.provider for r in records})
    return {name: ReplayProvider(name, records) for name in providers}


@dataclass(frozen=True)
class RecordDiff:
    field: str
    recorded: object
    replayed: object


@dataclass(frozen=True)
class ReplayVerification:
    matched: bool
    compared: int
    diffs: list[RecordDiff] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.matched


# Replay-critical fields — deterministic and reproducible. Latency/created_at are environmental and
# intentionally excluded from the byte-identity check.
_COMPARED_FIELDS = (
    "run_id",
    "llm_job",
    "attempt_index",
    "provider",
    "model_id",
    "prompt_version",
    "prompt_hash",
    "response_hash",
    "outcome",
)


def verify_replay(
    recorded: Iterable[CallRecord], replayed: Iterable[CallRecord]
) -> ReplayVerification:
    """Verify a replayed run reproduced the recorded one on every replay-critical field."""
    rec = list(recorded)
    rep = list(replayed)
    diffs: list[RecordDiff] = []
    if len(rec) != len(rep):
        diffs.append(RecordDiff("record_count", len(rec), len(rep)))
    for i, (a, b) in enumerate(zip(rec, rep, strict=False)):
        for name in _COMPARED_FIELDS:
            av = getattr(a, name)
            bv = getattr(b, name)
            if av != bv:
                diffs.append(RecordDiff(f"[{i}].{name}", av, bv))
    return ReplayVerification(matched=not diffs, compared=min(len(rec), len(rep)), diffs=diffs)
