"""ReplayHarness — re-run a stored run offline through ReplayProvider and verify equivalence (F2).

Reads the immutable Event Log for a ``run_id`` (``run_inputs.raw_snapshots`` + ``call_records``),
reconstructs the exact ``IngestBundle`` the run saw, wires a container whose only providers are
``ReplayProvider``s over the recorded Call Records, re-runs the pipeline with the same ``run_id``,
and verifies:
  - **deterministic equivalence** — the recomputed regime/scores/rules match the stored output
    byte-identically (the load-bearing replay property, database.md §5 / pipelines.md §5), and
  - **call-record equivalence** — the replayed Call Records reproduce the recorded ones on every
    replay-critical field (``verify_replay``).

No live provider is ever contacted (frozen invariant #6/#10). Reuses ``build_container``,
``ReplayProvider``, and ``verify_replay`` — no reimplementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from market_state_engine.app.container import build_container
from market_state_engine.core.dtos import MacroEvent, RawSnapshot
from market_state_engine.core.enums import RegimeState
from market_state_engine.core.hashing import content_hash
from market_state_engine.persistence.repositories import CallRecordRepository, RunRepository
from market_state_engine.persistence.session import Database
from market_state_engine.pipeline.orchestrator import IngestBundle
from market_state_engine.reasoning.adapters.replay import ReplayProvider
from market_state_engine.reasoning.models import CallRecord
from market_state_engine.reasoning.replay import ReplayVerification, verify_replay


@dataclass(frozen=True)
class ReplayResult:
    run_id: str
    # The FROZEN replay guarantee (database.md §5, ADR-011 DR-4): the sentiment-INDEPENDENT
    # deterministic core (regime, trend, risk, confidence, rules, causal links) reproduces
    # byte-identically. This is the load-bearing property and what ``deterministic_match`` tracks.
    deterministic_match: bool
    # Whether the FULL deterministic fingerprint (incl. MHI, which legitimately folds in sentiment)
    # also matched. This holds only when the LLM leg reproduced too — i.e. when every prompt input
    # was persisted in run_inputs. News items are not persisted in M5, so a run whose sentiment used
    # news will not reproduce the sentiment leg; its core still matches. Informational only.
    full_deterministic_match: bool
    call_records_match: bool
    stored_core_fingerprint: str
    replayed_core_fingerprint: str
    call_verification: ReplayVerification
    reproduced_is_degraded: bool

    @property
    def ok(self) -> bool:
        return self.deterministic_match


@dataclass
class LoadedRun:
    run_id: str
    ingest: IngestBundle
    call_records: list[CallRecord]
    stored_output: dict[str, object]
    previous_state: RegimeState | None = field(default=None)


class ReplayHarness:
    def __init__(self, root: Path, clock: Callable[[], datetime]) -> None:
        self._root = root
        self._clock = clock

    # --- loading (stored snapshots + call records) --------------------------------------
    def load(self, db: Database, run_id: str) -> LoadedRun:
        with db.session() as session:
            inputs = RunRepository(session).get_inputs(run_id)
            stored_output = RunRepository(session).get(run_id)
            raw_calls = CallRecordRepository(session).list_for_run(run_id)
        if inputs is None or stored_output is None:
            raise ValueError(f"run {run_id} has no stored inputs/output to replay")
        ingest = _rebuild_ingest(dict(inputs.raw_snapshots))
        records = [CallRecord.model_validate(r) for r in raw_calls]
        prev = _previous_state(stored_output)
        return LoadedRun(run_id, ingest, records, stored_output, prev)

    # --- execution (offline, ReplayProvider only) ---------------------------------------
    def replay(self, loaded: LoadedRun) -> ReplayResult:
        providers = sorted({r.provider for r in loaded.call_records})
        adapters = {name: ReplayProvider(name, loaded.call_records) for name in providers}

        sink: list[CallRecord] = []
        container = build_container(
            self._root,
            env="dev",
            ingest_provider=lambda ctx: loaded.ingest,
            overrides=adapters,
            clock=self._clock,
            previous_state_provider=lambda: loaded.previous_state,
        )
        # Capture the replay run's Call Records from the gateway sink.
        sink = container.call_record_sink
        summary = container.scheduler.run_replay(loaded.run_id)

        with container.database.session() as session:
            replayed_output = RunRepository(session).get(summary.run_id)
        assert replayed_output is not None

        stored_core = core_fingerprint(loaded.stored_output)
        replay_core = core_fingerprint(replayed_output)
        stored_full = deterministic_fingerprint(loaded.stored_output)
        replay_full = deterministic_fingerprint(replayed_output)
        replayed_records = list(sink)
        call_check = verify_replay(loaded.call_records, replayed_records)
        return ReplayResult(
            run_id=loaded.run_id,
            deterministic_match=(stored_core == replay_core),
            full_deterministic_match=(stored_full == replay_full),
            call_records_match=call_check.matched,
            stored_core_fingerprint=stored_core,
            replayed_core_fingerprint=replay_core,
            call_verification=call_check,
            reproduced_is_degraded=bool(replayed_output.get("is_degraded")),
        )

    def run(self, db: Database, run_id: str) -> ReplayResult:
        return self.replay(self.load(db, run_id))


# --- pure helpers --------------------------------------------------------------------
def deterministic_fingerprint(run: dict[str, object]) -> str:
    """Stable hash of the deterministic fields only (regime + per-asset scores/MHI/rules).

    Excludes LLM-produced fields (sentiment, summaries) and run identity/time so the fingerprint
    captures exactly the byte-identical-on-replay guarantee (ADR-011 DR-4).
    """
    assets = run.get("assets")
    asset_list = assets if isinstance(assets, list) else []
    regime = run.get("regime")
    regime_d = dict(regime) if isinstance(regime, dict) else {}
    payload = {
        "regime": {
            "state": regime_d.get("state"),
            "previous_state": regime_d.get("previous_state"),
            "changed_this_run": regime_d.get("changed_this_run"),
            "confidence": regime_d.get("confidence"),
            "drivers": regime_d.get("drivers"),
        },
        "assets": [
            {
                "symbol": a.get("symbol"),
                "trend": _scores(a).get("trend"),
                "risk": _scores(a).get("risk"),
                "confidence": _scores(a).get("confidence"),
                "market_health_index": a.get("market_health_index"),
                "activated_rules": a.get("activated_rules"),
                "causal_links": a.get("causal_links"),
            }
            for a in (dict(x) for x in asset_list if isinstance(x, dict))
        ],
    }
    return content_hash(payload)


def core_fingerprint(run: dict[str, object]) -> str:
    """Hash of the sentiment-independent core: regime + trend/risk/confidence + rules (no MHI).

    Used by the ablation runner: MHI legitimately shifts with sentiment (a real input to MHI), but
    trend/risk/regime/rules never depend on the LLM, so they are identical across every ablation
    variant over the same inputs.
    """
    assets = run.get("assets")
    asset_list = assets if isinstance(assets, list) else []
    regime = run.get("regime")
    regime_d = dict(regime) if isinstance(regime, dict) else {}
    payload = {
        "regime_state": regime_d.get("state"),
        "assets": [
            {
                "symbol": a.get("symbol"),
                "trend": _scores(a).get("trend"),
                "risk": _scores(a).get("risk"),
                "confidence": _scores(a).get("confidence"),
                "activated_rules": a.get("activated_rules"),
                "causal_links": a.get("causal_links"),
            }
            for a in (dict(x) for x in asset_list if isinstance(x, dict))
        ],
    }
    return content_hash(payload)


def _scores(asset: dict[str, object]) -> dict[str, object]:
    scores = asset.get("scores")
    return dict(scores) if isinstance(scores, dict) else {}


def _previous_state(stored_output: dict[str, object]) -> RegimeState | None:
    regime = stored_output.get("regime")
    if not isinstance(regime, dict):
        return None
    prev = regime.get("previous_state")
    return RegimeState(prev) if isinstance(prev, str) else None


def _rebuild_ingest(raw: dict[str, object]) -> IngestBundle:
    """Reconstruct the ``IngestBundle`` from a stored ``run_inputs.raw_snapshots`` document."""
    return IngestBundle(
        indicator_snapshots=_snapshots(raw.get("indicator_snapshots")),
        price_snapshots=_snapshots(raw.get("price_snapshots")),
        global_snapshots=_snapshots(raw.get("global_snapshots")),
        events=[MacroEvent.model_validate(e) for e in _as_list(raw.get("events"))],
        # news is not persisted in run_inputs (M5); deterministic output is unaffected
        news_items=[],
    )


def _snapshots(value: object) -> dict[str, RawSnapshot]:
    if not isinstance(value, dict):
        return {}
    return {str(k): RawSnapshot.model_validate(v) for k, v in value.items()}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []
