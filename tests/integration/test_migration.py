"""Migration verification (M5): the 0001 Alembic migration builds the full schema on SQLite."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

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
}


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
