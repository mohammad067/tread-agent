"""Safe Alembic bootstrap for fresh and legacy unversioned databases.

Fresh databases are created only by Alembic. A database previously created by
``Base.metadata.create_all`` is stamped at head only after its complete physical schema matches
the current migration head. Any mismatch fails before Alembic writes a revision marker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect

from .models import Base

_VERSION_TABLE = "alembic_version"


class SchemaCompatibilityError(RuntimeError):
    """An unversioned database cannot be safely mapped to the current migration head."""


def upgrade_or_baseline(engine: Engine, project_root: Path) -> str:
    """Upgrade a versioned/fresh database or safely baseline an exact legacy schema.

    Existing application data is never rewritten. For an unversioned database containing
    application tables, only the ``alembic_version`` marker is inserted, and only after complete
    table/column/key/index validation succeeds.
    """

    config = _config(project_root)
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration history has no head revision")

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        current = MigrationContext.configure(connection).get_current_revision()
        application_tables = set(inspect(connection).get_table_names()) - {_VERSION_TABLE}

        if current is None and application_tables:
            differences = schema_differences(connection)
            if differences:
                detail = "\n- ".join(differences)
                raise SchemaCompatibilityError(
                    "unversioned database schema does not match Alembic head; "
                    f"refusing to stamp:\n- {detail}"
                )
            command.stamp(config, head)
            return head

        command.upgrade(config, head)
        return head


def schema_differences(connection: Connection) -> list[str]:
    """Return deterministic physical differences from the current migration-head schema."""

    inspector = inspect(connection)
    expected_tables = set(Base.metadata.tables)
    actual_tables = set(inspector.get_table_names()) - {_VERSION_TABLE}
    differences: list[str] = []

    missing_tables = sorted(expected_tables - actual_tables)
    unexpected_tables = sorted(actual_tables - expected_tables)
    if missing_tables:
        differences.append(f"missing tables: {', '.join(missing_tables)}")
    if unexpected_tables:
        differences.append(f"unexpected tables: {', '.join(unexpected_tables)}")

    for table_name in sorted(expected_tables & actual_tables):
        expected_table = Base.metadata.tables[table_name]
        actual_columns = inspector.get_columns(table_name)
        actual_by_name = {str(column["name"]): column for column in actual_columns}
        expected_names = [column.name for column in expected_table.columns]
        actual_names = [str(column["name"]) for column in actual_columns]
        if actual_names != expected_names:
            differences.append(
                f"{table_name}: columns differ; expected {expected_names}, got {actual_names}"
            )
            continue

        for column in expected_table.columns:
            actual = actual_by_name[column.name]
            expected_type = _type_name(column.type.compile(dialect=connection.dialect))
            actual_type = _type_name(str(actual["type"]))
            if actual_type != expected_type:
                differences.append(
                    f"{table_name}.{column.name}: type expected {expected_type}, got {actual_type}"
                )
            if bool(actual["nullable"]) != bool(column.nullable):
                differences.append(
                    f"{table_name}.{column.name}: nullable expected "
                    f"{column.nullable}, got {actual['nullable']}"
                )

        expected_pk = tuple(column.name for column in expected_table.primary_key.columns)
        actual_pk = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
        if actual_pk != expected_pk:
            differences.append(f"{table_name}: primary key expected {expected_pk}, got {actual_pk}")

        expected_indexes = {
            str(index.name): (tuple(column.name for column in index.columns), bool(index.unique))
            for index in expected_table.indexes
        }
        actual_indexes = {
            str(index["name"]): (
                tuple(str(name) for name in index.get("column_names") or ()),
                bool(index.get("unique", False)),
            )
            for index in inspector.get_indexes(table_name)
        }
        if actual_indexes != expected_indexes:
            differences.append(
                f"{table_name}: indexes expected {_stable(expected_indexes)}, "
                f"got {_stable(actual_indexes)}"
            )

    return differences


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    return config


def _type_name(value: str) -> str:
    return " ".join(value.upper().replace("CHARACTER VARYING", "VARCHAR").split())


def _stable(value: dict[str, Any]) -> list[tuple[str, Any]]:
    return sorted(value.items())
