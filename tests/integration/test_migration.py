"""Migration verification (M5): the 0001 Alembic migration builds the full schema on SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from market_state_engine.persistence.migrations import (
    SchemaCompatibilityError,
    schema_differences,
    upgrade_or_baseline,
)
from market_state_engine.persistence.models import Base

REPO = Path(__file__).resolve().parents[2]

_EXPECTED_TABLES = {
    "runs",
    "run_inputs",
    "run_outputs",
    "call_records",
    "event_log",
    "news_items",
    "rule_activations",
    "total_mcap_samples",
    "last_good_snapshots",
    "macro_events",
}
_HEAD = "0005_macro_events"


def _config(db_path: Path) -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_migration_upgrade_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "mse.db"
    command.upgrade(_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert tables >= _EXPECTED_TABLES
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == _HEAD
        assert schema_differences(connection) == []


def test_migration_downgrade_removes_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "mse.db"
    cfg = _config(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(f"sqlite:///{db_path}")
    remaining = set(inspect(engine).get_table_names())
    assert not (_EXPECTED_TABLES & remaining)


def test_runs_table_has_m2_field_additions(tmp_path: Path) -> None:
    db_path = tmp_path / "mse.db"
    command.upgrade(_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    cols = {c["name"] for c in inspect(engine).get_columns("runs")}
    assert {"is_degraded", "provider_version", "model_version", "pricing_version"} <= cols


def test_macro_events_table_matches_persistence_contract(tmp_path: Path) -> None:
    db_path = tmp_path / "mse.db"
    command.upgrade(_config(db_path), "head")
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("macro_events")}
    indexes = {index["name"] for index in inspector.get_indexes("macro_events")}

    assert columns == {
        "event_id",
        "event_type",
        "scheduled_at",
        "consensus",
        "actual",
        "surprise",
        "entered_by",
        "raw",
        "ingested_at",
    }
    assert "ix_macro_events_type_scheduled" in indexes


def test_compatible_unversioned_database_is_stamped_without_losing_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO event_log (run_id, event_type, payload, created_at) "
                "VALUES (NULL, 'legacy', '{}', '2026-08-20T00:00:00Z')"
            )
        )
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )

    revision = upgrade_or_baseline(engine, REPO)

    assert revision == _HEAD
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == _HEAD
        count = connection.execute(text("SELECT COUNT(*) FROM event_log")).scalar_one()
        assert count == 1
        assert schema_differences(connection) == []


def test_incompatible_unversioned_database_is_rejected_without_stamp(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "incompatible.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE runs (run_id VARCHAR(26) PRIMARY KEY)"))

    with pytest.raises(SchemaCompatibilityError, match="missing tables"):
        upgrade_or_baseline(engine, REPO)

    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() is None
        assert "runs" in inspect(connection).get_table_names()


def test_versioned_upgrade_preserves_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "versioned.db"
    cfg = _config(db_path)
    command.upgrade(cfg, "0001_initial")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO event_log (run_id, event_type, payload, created_at) "
                "VALUES (NULL, 'before_upgrade', '{}', '2026-08-20T00:00:00Z')"
            )
        )

    revision = upgrade_or_baseline(engine, REPO)

    assert revision == _HEAD
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM event_log")).scalar_one()
        assert count == 1
        assert MigrationContext.configure(connection).get_current_revision() == _HEAD
