"""Replay verification (M5): re-run the complete pipeline through ReplayProvider, no live calls.

A live run records Call Records; a replay container rebuilt from those records reproduces the run
with no live provider contacted (frozen invariant #6). Deterministic fields are byte-identical.
"""

from __future__ import annotations

from market_state_engine.app.container import build_container
from market_state_engine.core.enums import RegimeState
from market_state_engine.core.hashing import content_hash
from market_state_engine.persistence.repositories import CallRecordRepository, RunRepository
from market_state_engine.reasoning.adapters.replay import ReplayProvider
from market_state_engine.reasoning.models import CallRecord

from ._harness import REPO, build_full_container, fixed_clock, ingest_provider


def _load_call_records(container: object, run_id: str) -> list[CallRecord]:
    with container.database.session() as s:  # type: ignore[attr-defined]
        raw = CallRecordRepository(s).list_for_run(run_id)
    return [CallRecord.model_validate(r) for r in raw]


def test_replay_reruns_full_pipeline_without_live_provider() -> None:
    # 1) Live run with a fixed run_id (replay keys prompts by hash, which embeds the run_id).
    run_id = "01J8ZK3W9P4Q5R6S7T8U9V0W1X"
    live = build_full_container()
    live_summary = live.scheduler.run_manual(run_id=run_id)
    records = _load_call_records(live, live_summary.run_id)
    assert len(records) == 2

    # 2) Replay container: adapters are ReplayProviders over the recorded Call Records. Same run_id
    #    → identical prompts → identical prompt hashes → the recorded calls are served.
    replay_adapters = {"anthropic": ReplayProvider("anthropic", records)}
    replay = build_container(
        REPO,
        env="dev",
        ingest_provider=ingest_provider,
        overrides=replay_adapters,
        clock=fixed_clock,
        previous_state_provider=lambda: RegimeState.TRANSITION,
    )
    replay_summary = replay.scheduler.run_manual(run_id=run_id)

    with live.database.session() as s:
        live_run = RunRepository(s).get(live_summary.run_id)
    with replay.database.session() as s:
        replay_run = RunRepository(s).get(replay_summary.run_id)

    assert live_run is not None and replay_run is not None
    # Replay reproduced a full (non-degraded) run.
    assert replay_run["is_degraded"] is False
    # Deterministic fields byte-identical (ignore run identity/time which differ by construction).
    assert _det_fingerprint(live_run) == _det_fingerprint(replay_run)


def _det_fingerprint(run: dict[str, object]) -> str:
    assets = run["assets"]
    payload = {
        "regime_state": run["regime"]["state"],  # type: ignore[index]
        "assets": [
            {
                "symbol": a["symbol"],
                "scores": a["scores"],
                "market_health_index": a["market_health_index"],
                "activated_rules": a["activated_rules"],
            }
            for a in assets  # type: ignore[union-attr]
        ],
    }
    return content_hash(payload)
