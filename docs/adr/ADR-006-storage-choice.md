# ADR-006: Storage technology choice (SQLite → Postgres, one codebase)

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, Senior Backend Engineer
- **Related:** ADR-004 (replay), ADR-010 (deployment); challenge A1 (staged ops)

## Context
The system must persist runs, immutable input/output snapshots, Call Records, outcomes, versions, news, events,
and evaluation reports — with **append-only** guarantees for replay. MVP write volume is tiny (~4 runs/day),
but the product must scale to production and support backups/DR (§12).

## Decision
**One SQLAlchemy codebase**, dialect-neutral, with **SQLite for dev/CI** and **PostgreSQL 16 for
staging/prod**. Alembic migrations. JSON documents for snapshots/outputs (portable `JSON`/`JSONB` variant),
typed columns for queryable metadata. Postgres, DR rehearsal, and heavy ops are **staged to M5/M7** (A1).

## Alternatives Considered
- **Postgres everywhere (incl. dev/CI)**: rejected — heavier local/CI for no MVP benefit; violates "simpler
  when equal" for dev (A1).
- **SQLite everywhere**: rejected — insufficient for prod concurrency/backups/DR.
- **NoSQL/document store**: rejected — evaluation relies on relational joins across runs/outcomes/versions;
  loses integrity and typed queries.

## Consequences
- (+) Zero-ops hermetic dev/CI; clean path to prod with no rewrite; append-only tables backed up for replay.
- (−) Must avoid dialect-specific SQL to keep the path clean (JSON type variants, no vendor-only features);
  a documented constraint on all persistence code.
