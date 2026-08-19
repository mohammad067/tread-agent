"""RunService — execute one pipeline run end to end and persist it (module-catalog E1).

Wraps the ``PipelineOrchestrator`` with the Event Log + repositories: it records lifecycle events
(start/finish/failure/degraded/provider-calls/replay), persists ``run_inputs``/``run_outputs``,
Call Records, and rule activations, and enforces idempotency (re-running an existing ``run_id`` is a
no-op — pipelines.md §1). It contains no market math; all numbers come from the orchestrator/core.

Call Records are collected via the gateway's recorder sink (a list the composition root wires); the
service drains that sink after each run and persists every attempt (append-only, ADR-007 D-6).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ulid import ULID

from market_state_engine.core.run_context import RunContext
from market_state_engine.persistence.repositories import (
    CallRecordRepository,
    EventLogRepository,
    RuleActivationRepository,
    RunRepository,
)
from market_state_engine.persistence.session import Database
from market_state_engine.reasoning.models import CallRecord

from .events import EventRecorder, EventType
from .orchestrator import IngestBundle, PipelineOrchestrator


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    is_degraded: bool
    published: bool
    idempotent_noop: bool = False


class RunService:
    def __init__(
        self,
        db: Database,
        orchestrator: PipelineOrchestrator,
        clock: Callable[[], datetime],
        call_record_sink: list[CallRecord],
        *,
        pipeline_version: str = "1.1.0",
        replay: bool = False,
    ) -> None:
        self._db = db
        self._orchestrator = orchestrator
        self._clock = clock
        self._sink = call_record_sink
        self._pipeline_version = pipeline_version
        self._replay = replay

    def execute(self, ctx: RunContext, ingest: IngestBundle) -> RunSummary:
        now_iso = self._now_iso()
        self._sink.clear()

        with self._db.session() as session:
            events = EventRecorder(EventLogRepository(session), self._clock)
            runs = RunRepository(session)

            # Idempotency: re-triggering an existing run_id is a no-op (pipelines.md §1).
            if runs.exists(ctx.run_id):
                events.record(EventType.SCHEDULER, {"idempotent_noop": True}, run_id=ctx.run_id)
                return RunSummary(ctx.run_id, "exists", False, True, idempotent_noop=True)

            events.record(
                EventType.REPLAY if self._replay else EventType.RUN_START,
                {"trigger_type": ctx.trigger_type.value, "run_sequence": ctx.run_sequence},
                run_id=ctx.run_id,
            )

            try:
                result = self._orchestrator.run(ctx, ingest)
            except Exception as exc:  # persistence/orchestration failure — record + re-raise safely
                events.record(
                    EventType.RUN_FAILURE, {"error": type(exc).__name__}, run_id=ctx.run_id
                )
                raise

            # Normalize to JSON-native form (enums → their string values) so typed columns and the
            # stored document are contract-faithful and match what the API serves.
            doc = json.loads(json.dumps(result.run.to_contract_dict()))
            status = "degraded" if result.is_degraded else "published"

            # 9 Persist: runs + immutable inputs/outputs + call records + activations.
            runs.add_run(doc, status=status, pipeline_version=self._pipeline_version)
            runs.add_inputs(
                ctx.run_id,
                raw_snapshots=_ingest_snapshot(ingest),
                data_gaps=_collect_data_gaps(doc),
                deviation_flags=[],
                ingested_at=now_iso,
            )
            runs.add_output(doc, persisted_at=now_iso)
            RuleActivationRepository(session).add_for_run(ctx.run_id, doc, created_at=now_iso)

            call_repo = CallRecordRepository(session)
            for record in self._sink:
                events.record(
                    EventType.PROVIDER_CALL,
                    {"provider": record.provider, "outcome": record.outcome},
                    run_id=ctx.run_id,
                )
                call_repo.add(str(ULID()), json.loads(json.dumps(record.to_contract_dict())))

            if result.is_degraded:
                events.record(EventType.DEGRADED, {"reason": "llm_absent"}, run_id=ctx.run_id)
            events.record(
                EventType.RUN_FINISH,
                {"status": status, "published": result.published},
                run_id=ctx.run_id,
            )

        return RunSummary(ctx.run_id, status, result.is_degraded, result.published)

    def _now_iso(self) -> str:
        return self._clock().isoformat().replace("+00:00", "Z")


def _ingest_snapshot(ingest: IngestBundle) -> dict[str, object]:
    """Serialize the raw inputs verbatim for byte-identical replay (database.md §4.2)."""
    return {
        "indicator_snapshots": {
            s: snap.model_dump(by_alias=True) for s, snap in ingest.indicator_snapshots.items()
        },
        "price_snapshots": {
            s: snap.model_dump(by_alias=True) for s, snap in ingest.price_snapshots.items()
        },
        "global_snapshots": {
            s: snap.model_dump(by_alias=True) for s, snap in ingest.global_snapshots.items()
        },
        "events": [e.model_dump(by_alias=True) for e in ingest.events],
        # Preserve normalized news in its original deterministic order. Replay
        # must rebuild the same NewsDigest and therefore the same prompt hash
        # without fetching any live feed.
        "news_items": [item.model_dump(by_alias=True) for item in ingest.news_items],
    }


def _collect_data_gaps(doc: dict[str, object]) -> list[object]:
    gaps: list[object] = []
    assets = doc.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        a = dict(asset) if isinstance(asset, dict) else {}
        asset_gaps = a.get("data_gaps")
        for gap in asset_gaps if isinstance(asset_gaps, list) else []:
            gaps.append({"symbol": a.get("symbol"), "gap": gap})
    return gaps
