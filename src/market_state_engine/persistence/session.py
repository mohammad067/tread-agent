"""Engine + session management (database.md §1, ADR-006).

One SQLAlchemy codebase across dialects. The DSN is resolved from configuration/environment — never
hardcoded: SQLite (``dialect: sqlite``) uses a file path (or in-memory for tests); Postgres uses the
DSN from the env var named in config. ``create_all`` builds the schema for dev/CI; production uses
the Alembic migration (``migrations/``) that mirrors these models.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


def build_engine(url: str) -> Engine:
    """Create an engine for the given SQLAlchemy URL.

    In-memory SQLite is per-connection, so a shared ``StaticPool`` keeps every session on the one
    connection (otherwise each session sees an empty database). File/Postgres URLs pool normally.
    """
    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {"future": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    return create_engine(url, connect_args=connect_args, **kwargs)


def resolve_url(dialect: str, dsn_env: str | None = None, sqlite_path: str | None = None) -> str:
    """Resolve a SQLAlchemy URL from config, reading any DSN from the env (no inline secrets)."""
    if dialect == "sqlite":
        target = sqlite_path or ":memory:"
        return f"sqlite:///{target}"
    if dsn_env is None:
        raise ValueError(
            f"dialect {dialect!r} requires a dsn_env naming the DSN environment variable"
        )
    dsn = os.environ.get(dsn_env)
    if not dsn:
        raise ValueError(f"environment variable {dsn_env} is unset for dialect {dialect!r}")
    return dsn


def create_all(engine: Engine) -> None:
    """Create every table (dev/CI convenience; prod uses the Alembic migration)."""
    Base.metadata.create_all(engine)


class Database:
    """Owns an engine + session factory; hands out short-lived sessions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all(self) -> None:
        create_all(self._engine)
