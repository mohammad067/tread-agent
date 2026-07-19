# Architecture Documentation — Market State Engine

> **Milestone 1 — Architecture Foundation.** Production-ready architecture specification and the basis for all
> later development. **No application code** — design, engineering decisions, diagrams, component
> responsibilities, data flow, dependencies. Fully consistent with Milestone 0 and the frozen provider
> architecture. **API-only, no front-end** ([../adr/ADR-012](../adr/ADR-012-api-only-no-frontend.md)).

## Documents

| # | Document | Covers (M1 request items) |
|---|----------|---------------------------|
| 1 | [overview.md](overview.md) | High-level architecture (1), component diagram (2), backend + clean/layered architecture (3,4), tech stack + rationale (6), dependency rules (30) |
| 2 | [module-catalog.md](module-catalog.md) | Component responsibilities (29), dependency rules (30) |
| 3 | [database.md](database.md) | Database architecture (7), ER diagram (8), all tables (9) |
| 4 | [api-design.md](api-design.md) | API design (10), endpoint catalog (11) |
| 5 | [pipelines.md](pipelines.md) | Scheduler (12), Rule Engine (13), News ingestion (15), Market State generation (16), Replay (17), Evaluation (18), Event Log (19) |
| 6 | [llm-provider-architecture.md](llm-provider-architecture.md) | **FROZEN** LLM architecture (14) — provider-agnostic |
| 7 | [llm-architecture-m1.md](llm-architecture-m1.md) | LLM architecture (14) — M1 application-side placement |
| 8 | [cross-cutting.md](cross-cutting.md) | Configuration management (20), error handling (21), logging (22), observability (23), monitoring (24), security (25) |
| 9 | [deployment.md](deployment.md) | Folder structure (5), Docker architecture (26), deployment architecture (27) |
| 10 | [sequence-diagrams.md](sequence-diagrams.md) | Sequence diagrams (28) |
| 11 | [evolution-roadmap.md](evolution-roadmap.md) | Evolution roadmap, feature→component traceability, implementation plan (32), **Open Questions** |
| — | [../adr/](../adr/) | ADRs required for Milestone 1 (31): ADR-001…013 |

## The load-bearing invariants (read these first)

1. **Clean-Architecture dependency rule** — the Domain Core depends on nothing external; it reaches the LLM
   only through `MarketReasoner`. ([overview.md §2](overview.md), [module-catalog.md](module-catalog.md))
2. **Frozen provider boundary** — no vendor SDK outside `reasoning/adapters/`; providers are config; add-a-
   provider = one adapter + one config entry. ([ADR-007](../adr/ADR-007-provider-agnostic-llm-gateway.md))
3. **Never abort on provider failure** — failover → Degraded Run (deterministic-only, honest absence).
   ([ADR-011](../adr/ADR-011-degraded-run-failure-isolation.md))
4. **Everything replayable** — immutable input snapshots + Call Records in an append-only Event Log.
   ([ADR-004](../adr/ADR-004-replay-immutable-snapshots.md))
5. **API-only** — the JSON contract + REST is the entire consumer surface; UX rules become consumer
   obligations. ([ADR-012](../adr/ADR-012-api-only-no-frontend.md))

## Status

- **Milestone 0** (product) — complete, in [../product/](../product/).
- **Provider freeze** — complete (ADR-007, ADR-011, [llm-provider-architecture.md](llm-provider-architecture.md)).
- **Milestone 1** (this set) — complete, **awaiting review**. No code.
- **O1 / D1 / D2 resolved & frozen** ([ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md)):
  FA-only summary, USD/IRR in IRT, proxy internal-only.
- **Next:** Milestone 2 (Contracts & Schemas) — **in progress**; schema-blocking items are closed.
