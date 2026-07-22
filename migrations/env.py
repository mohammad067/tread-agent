"""Alembic environment — offline/online migration runner (database.md §B).

Uses the ORM ``Base.metadata`` as the autogenerate target and reads the URL from the Alembic config
(set programmatically or via ``sqlalchemy.url``). Dialect-neutral so the same migration runs on
SQLite (dev/CI) and Postgres (prod).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from market_state_engine.persistence.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
