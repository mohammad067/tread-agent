"""The DI container — constructs and holds the wired service graph (composition root).

Built from the existing configuration system only: ``load_config_bundle`` + ``load_env_config`` +
``ReasoningPaths``. Two reasoning modes: live (config-driven adapters, with optional offline
overrides) and replay (``ReplayProvider`` over recorded Call Records). Time is injectable so the
graph is deterministic in tests. The container owns nothing stateful beyond the DB + registries.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from market_state_engine.config.loader import ConfigBundle, load_config_bundle, load_env_config
from market_state_engine.core.enums import RegimeState
from market_state_engine.core.run_context import RunContext
from market_state_engine.observability.metrics import Metrics
from market_state_engine.persistence.migrations import upgrade_or_baseline
from market_state_engine.persistence.repositories import RunRepository
from market_state_engine.persistence.session import Database, build_engine, resolve_url
from market_state_engine.pipeline.event_trigger import EventTrigger
from market_state_engine.pipeline.orchestrator import IngestBundle, PipelineOrchestrator
from market_state_engine.pipeline.runner import RunService
from market_state_engine.pipeline.scheduler import Scheduler
from market_state_engine.reasoning import ReasoningPaths, build_gateway
from market_state_engine.reasoning.adapters.base import ProviderAdapter
from market_state_engine.reasoning.gateway import LLMGateway
from market_state_engine.reasoning.models import CallRecord
from market_state_engine.rules.engine import RuleEngine
from market_state_engine.rules.loader import load_rulebook, read_rulebook_version

_PIPELINE_VERSION = "1.2.0"


def _utc_now() -> datetime:  # pragma: no cover - trivial default, overridden in tests
    return datetime.now(timezone.utc)


class Container:
    """Holds the wired graph. Construct via :func:`build_container`."""

    def __init__(
        self,
        *,
        config: ConfigBundle,
        database: Database,
        gateway: LLMGateway,
        scheduler: Scheduler,
        run_service: RunService,
        call_record_sink: list[CallRecord],
        metrics: Metrics,
        rulebook_version: str,
        pipeline_version: str,
        event_trigger: EventTrigger,
    ) -> None:
        self.config = config
        self.database = database
        self.gateway = gateway
        self.scheduler = scheduler
        self.run_service = run_service
        self.call_record_sink = call_record_sink
        self.metrics = metrics
        self.rulebook_version = rulebook_version
        self.pipeline_version = pipeline_version
        self.event_trigger = event_trigger


def build_container(
    root: Path,
    *,
    env: str = "dev",
    ingest_provider: Callable[[RunContext], IngestBundle] | None = None,
    ingest_provider_factory: (
        Callable[[Database, ConfigBundle], Callable[[RunContext], IngestBundle]] | None
    ) = None,
    overrides: Mapping[str, ProviderAdapter] | None = None,
    clock: Callable[[], datetime] = _utc_now,
    previous_state_provider: Callable[[], RegimeState | None] | None = None,
    sqlite_path: str | None = None,
    create_schema: bool = True,
    migrate_schema: bool = False,
) -> Container:
    """Wire the full service graph from config. ``ingest_provider`` supplies raw inputs per run."""
    config_dir = root / "config"
    config = load_config_bundle(config_dir)
    env_cfg = load_env_config(config_dir, env)
    rules_dir = root / "rules"
    rulebook_version = read_rulebook_version(rules_dir)
    rule_engine = RuleEngine(load_rulebook(rules_dir))

    # Database from env config (dialect + optional DSN env var). No hardcoded connection string.
    url = resolve_url(env_cfg.database.dialect, env_cfg.database.dsn_env, sqlite_path)
    database = Database(build_engine(url))
    if create_schema and migrate_schema:
        raise ValueError("create_schema and migrate_schema are mutually exclusive")
    if migrate_schema:
        upgrade_or_baseline(database.engine, root)
    elif create_schema:
        if env == "prod":
            raise ValueError("production schema must be managed by Alembic migrations")
        database.create_all()

    # Reasoning gateway: config-driven; the recorder sink collects Call Records for persistence.
    sink: list[CallRecord] = []
    gateway = build_gateway(
        ReasoningPaths(root),
        overrides=dict(overrides) if overrides is not None else None,
        recorder=sink.append,
        clock=clock,
    )

    orchestrator = PipelineOrchestrator(
        config=config,
        rules=rule_engine,
        reasoner=gateway,
        rulebook_version=rulebook_version,
        clock=clock,
    )
    run_service = RunService(
        db=database,
        orchestrator=orchestrator,
        clock=clock,
        call_record_sink=sink,
        pipeline_version=_PIPELINE_VERSION,
    )
    if (ingest_provider is None) == (ingest_provider_factory is None):
        raise ValueError("provide exactly one of ingest_provider or ingest_provider_factory")
    resolved_ingest = (
        ingest_provider
        if ingest_provider is not None
        else ingest_provider_factory(database, config)  # type: ignore[misc]
    )

    def _next_run_sequence() -> int:
        with database.session() as session:
            return RunRepository(session).next_sequence()

    scheduler = Scheduler(
        run_service=run_service,
        ingest_provider=resolved_ingest,
        clock=clock,
        run_sequence_provider=_next_run_sequence,
        previous_state_provider=previous_state_provider,
        versions={"pipeline": _PIPELINE_VERSION, "rulebook": rulebook_version},
    )
    event_trigger = EventTrigger(
        database,
        scheduler,
        clock,
        cooldown_minutes=env_cfg.scheduler.event_cooldown_minutes,
    )
    return Container(
        config=config,
        database=database,
        gateway=gateway,
        scheduler=scheduler,
        run_service=run_service,
        call_record_sink=sink,
        metrics=Metrics(),
        rulebook_version=rulebook_version,
        pipeline_version=_PIPELINE_VERSION,
        event_trigger=event_trigger,
    )
