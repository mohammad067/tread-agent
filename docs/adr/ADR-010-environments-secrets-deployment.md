# ADR-010: Environments, secrets, and deployment model

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, Senior Backend Engineer
- **Related:** ADR-006 (storage); challenge A1 (staged ops); ADR-012 (API-only)

## Context
The system needs reproducible environments, safe secret handling, and a deployment contract — without
over-engineering a single-node MVP that runs ~4 times/day (§3, A1).

## Decision
- **Three environments:** `dev` (SQLite, mock ingestors, mock/deterministic LLM) → `staging` (Postgres, real
  sources, cheap model) → `prod`. Non-secret per-env config in `config/environments/`.
- **12-factor secrets:** all secrets (provider keys, kifpool key, DB DSN) via **environment variables only**;
  `.env.example` documents every variable; real secrets never in repo/config/logs.
- **Deployment:** Docker **multi-stage, non-root** image; **`docker-compose`** (app + postgres + scheduler) is
  the deployment contract. **Single-node is acceptable for MVP** (§3).
- **Staged ops (A1):** Postgres, rate limiting, DR rehearsal, metrics/dashboards land in **M5/M7**; the design
  slots exist from M1 so nothing is retrofitted.

## Alternatives Considered
- **Kubernetes / multi-node now**: rejected — over-engineered for MVP; horizontal scaling is a non-goal (§3).
- **Secrets in config files**: rejected — violates 12-factor and §12 security.
- **Postgres/observability from day one everywhere**: rejected — heavier dev/CI for no MVP value (A1).

## Consequences
- (+) Reproducible envs; safe secrets; a concrete, reviewable deployment contract; clean path to prod.
- (−) Single-node has a scheduling single-point-of-failure — mitigated by missed-run detection + idempotent
  re-trigger. Revisit only if availability/scaling needs exceed the MVP's stated non-goals.
