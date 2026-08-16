"""Repositories — thin, business-logic-free read/write over the ORM rows (module-catalog D1).

Each repository maps a contract-shaped object (a ``MarketStateRun`` dict, a ``CallRecord``, event)
to/from its row. Append-only tables expose ``add`` (insert) + reads only — no update path (db
§B.2, enforced here rather than by convention). Repositories never compute market numbers, render
prompts, or call providers; they persist what the pipeline already produced.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_state_engine.core.dtos import TotalMcapSample
from market_state_engine.core.hashing import content_hash

from .models import (
    CallRecordRow,
    EventLogRow,
    NewsItemRow,
    RuleActivationRow,
    RunInputRow,
    RunOutputRow,
    RunRow,
    TotalMcapSampleRow,
)


class RunRepository:
    """``runs`` + immutable ``run_inputs``/``run_outputs`` (Event Log snapshot/output tables)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add_run(
        self,
        market_state_run: dict[str, object],
        *,
        status: str,
        pipeline_version: str,
    ) -> RunRow:
        versions = _as_dict(market_state_run.get("versions"))
        trigger_detail = _as_dict(market_state_run.get("trigger_detail"))
        row = RunRow(
            run_id=str(market_state_run["run_id"]),
            run_sequence=_as_int(market_state_run.get("run_sequence")),
            trigger_type=str(market_state_run["trigger_type"]),
            trigger_detail=trigger_detail,
            generated_at=str(market_state_run["generated_at"]),
            schema_version=str(market_state_run["schema_version"]),
            pipeline_version=pipeline_version,
            provider_version=_opt(versions.get("provider")),
            model_version=_opt(versions.get("model")),
            prompt_sentiment_version=str(versions.get("prompt_sentiment", "")),
            prompt_synthesis_version=str(versions.get("prompt_synthesis", "")),
            rulebook_version=str(versions.get("rulebook", "")),
            mhi_weights_version=str(versions.get("mhi_weights", "")),
            pricing_version=_opt(versions.get("pricing")),
            status=status,
            is_degraded=bool(market_state_run["is_degraded"]),
        )
        self._s.add(row)
        return row

    def add_output(self, market_state_run: dict[str, object], *, persisted_at: str) -> RunOutputRow:
        row = RunOutputRow(
            run_id=str(market_state_run["run_id"]),
            market_state_run=market_state_run,
            guardrail_flags=list(_as_list(market_state_run.get("guardrail_flags"))),
            output_hash=content_hash(market_state_run),
            persisted_at=persisted_at,
        )
        self._s.add(row)
        return row

    def add_inputs(
        self,
        run_id: str,
        *,
        raw_snapshots: dict[str, object],
        data_gaps: list[object],
        deviation_flags: list[object],
        ingested_at: str,
    ) -> RunInputRow:
        row = RunInputRow(
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            snapshot_hash=content_hash(raw_snapshots),
            data_gaps=data_gaps,
            deviation_flags=deviation_flags,
            ingested_at=ingested_at,
        )
        self._s.add(row)
        return row

    def get(self, run_id: str) -> dict[str, object] | None:
        row = self._s.get(RunOutputRow, run_id)
        return dict(row.market_state_run) if row is not None else None

    def get_inputs(self, run_id: str) -> RunInputRow | None:
        return self._s.get(RunInputRow, run_id)

    def latest(self) -> dict[str, object] | None:
        stmt = select(RunRow.run_id).order_by(RunRow.run_sequence.desc()).limit(1)
        run_id = self._s.execute(stmt).scalar_one_or_none()
        return self.get(run_id) if run_id is not None else None

    def list_runs(
        self,
        *,
        trigger_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        stmt = select(RunRow.run_id).order_by(RunRow.run_sequence.desc())
        if trigger_type is not None:
            stmt = stmt.where(RunRow.trigger_type == trigger_type)
        stmt = stmt.offset(offset).limit(limit)
        ids = list(self._s.execute(stmt).scalars().all())
        outputs = [self.get(rid) for rid in ids]
        return [o for o in outputs if o is not None]

    def exists(self, run_id: str) -> bool:
        return self._s.get(RunRow, run_id) is not None

    def next_sequence(self) -> int:
        stmt = select(RunRow.run_sequence).order_by(RunRow.run_sequence.desc()).limit(1)
        current = self._s.execute(stmt).scalar_one_or_none()
        return (current or 0) + 1


class CallRecordRepository:
    """``call_records`` — append-only per-attempt rows."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, call_id: str, record: dict[str, object]) -> CallRecordRow:
        row = CallRecordRow(call_id=call_id, **_call_record_fields(record))
        self._s.add(row)
        return row

    def list_for_run(self, run_id: str) -> list[dict[str, object]]:
        stmt = (
            select(CallRecordRow)
            .where(CallRecordRow.run_id == run_id)
            .order_by(CallRecordRow.created_at, CallRecordRow.attempt_index)
        )
        return [_call_record_to_dict(r) for r in self._s.execute(stmt).scalars().all()]


class EventLogRepository:
    """``event_log`` — append-only lifecycle event stream."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add(
        self,
        event_type: str,
        payload: dict[str, object],
        *,
        created_at: str,
        run_id: str | None = None,
    ) -> EventLogRow:
        row = EventLogRow(
            run_id=run_id, event_type=event_type, payload=payload, created_at=created_at
        )
        self._s.add(row)
        return row

    def list_for_run(self, run_id: str) -> list[EventLogRow]:
        stmt = (
            select(EventLogRow).where(EventLogRow.run_id == run_id).order_by(EventLogRow.event_seq)
        )
        return list(self._s.execute(stmt).scalars().all())

    def count(self) -> int:
        return len(list(self._s.execute(select(EventLogRow.event_seq)).scalars().all()))


class NewsRepository:
    """``news_items`` — ingested feed records (idempotent upsert by news_id)."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, item: dict[str, object], *, ingested_at: str) -> NewsItemRow:
        news_id = str(item["news_id"])
        existing = self._s.get(NewsItemRow, news_id)
        if existing is not None:
            return existing
        row = NewsItemRow(
            news_id=news_id,
            source=str(item["source"]),
            url=_opt(item.get("url")),
            title=str(item["title"]),
            published_at=str(item["published_at"]),
            source_quality=_opt_float(item.get("source_quality")),
            raw=dict(item),
            ingested_at=ingested_at,
        )
        self._s.add(row)
        return row

    def get(self, news_id: str) -> NewsItemRow | None:
        return self._s.get(NewsItemRow, news_id)


class RuleActivationRepository:
    """``rule_activations`` — append-only queryable projection of a run's activated rules."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def add_for_run(
        self, run_id: str, market_state_run: dict[str, object], *, created_at: str
    ) -> int:
        count = 0
        for asset in _as_list(market_state_run.get("assets")):
            asset_d = _as_dict(asset)
            symbol = str(asset_d.get("symbol", ""))
            for activation in _as_list(asset_d.get("activated_rules")):
                act = _as_dict(activation)
                self._s.add(
                    RuleActivationRow(
                        run_id=run_id,
                        symbol=symbol,
                        rule_id=str(act["rule_id"]),
                        strength=str(act["strength"]),
                        horizon=str(act["horizon"]),
                        decay_remaining=float(act["decay_remaining"]),  # type: ignore[arg-type]
                        created_at=created_at,
                    )
                )
                count += 1
        return count

    def list_for_run(self, run_id: str) -> list[RuleActivationRow]:
        stmt = select(RuleActivationRow).where(RuleActivationRow.run_id == run_id)
        return list(self._s.execute(stmt).scalars().all())


class TotalMcapSampleRepository:
    """Idempotent TOTAL_MCAP sample storage and bounded chronological reads."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, sample: TotalMcapSample) -> TotalMcapSampleRow:
        key = (sample.symbol, sample.as_of)
        row = self._s.get(TotalMcapSampleRow, key)
        if row is None:
            row = TotalMcapSampleRow(
                symbol=sample.symbol,
                value=sample.value,
                as_of=sample.as_of,
                run_id=sample.run_id,
            )
            self._s.add(row)
        else:
            row.value = sample.value
            row.run_id = sample.run_id
        self._s.flush()
        return row

    def list_recent(self, symbol: str, *, limit: int = 130) -> list[TotalMcapSample]:
        stmt = (
            select(TotalMcapSampleRow)
            .where(TotalMcapSampleRow.symbol == symbol)
            .order_by(TotalMcapSampleRow.as_of.desc())
            .limit(limit)
        )
        rows = list(reversed(self._s.execute(stmt).scalars().all()))
        return [
            TotalMcapSample(
                symbol=row.symbol,
                value=row.value,
                as_of=row.as_of,
                run_id=row.run_id,
            )
            for row in rows
        ]


# --- helpers -------------------------------------------------------------------------
_CALL_RECORD_FIELDS = (
    "run_id",
    "llm_job",
    "attempt_index",
    "provider",
    "model_id",
    "prompt_version",
    "prompt_hash",
    "rendered_prompt",
    "response",
    "response_hash",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "estimated_cost",
    "retries",
    "finish_reason",
    "outcome",
    "created_at",
)


def _call_record_fields(record: dict[str, object]) -> dict[str, object]:
    return {k: record.get(k) for k in _CALL_RECORD_FIELDS}


def _call_record_to_dict(row: CallRecordRow) -> dict[str, object]:
    return {k: getattr(row, k) for k in _CALL_RECORD_FIELDS}


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _opt(value: object) -> str | None:
    return str(value) if value is not None else None


def _opt_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0
