"""Persistence layer — SQLAlchemy models, session management, and repositories (M5).

Realizes the frozen DB design ([docs/architecture/database.md]) exactly: one dialect-neutral
SQLAlchemy codebase (SQLite dev → Postgres prod, ADR-006), append-only Event Log tables
(``run_inputs``, ``run_outputs``, ``call_records``) with no ORM UPDATE path, everything versioned.
Repositories hold no business logic — they read/write the contract-shaped rows the pipeline makes.
The deterministic core never imports this package (import-linter enforced).
"""
