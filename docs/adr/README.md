# Architecture Decision Records (ADR Log)

> Every significant decision — technical or product — is a numbered ADR here.
> **Format:** Title / Status (Proposed \| Accepted \| Superseded) / Context / Decision / Alternatives Considered
> / Consequences. **ADRs are immutable once Accepted; reversal = a new superseding ADR.**
>
> **Milestone status:** We are between Milestone 0 (product foundation, complete) and Milestone 1
> (architecture foundation, not yet started). Most ADRs below are **seeded as `Proposed`** and will be written
> in full and Accepted during Milestone 1. **Exceptions:** ADR-007 and ADR-011 are **Accepted now** because
> the user explicitly asked to *freeze* the LLM-provider-independence architecture ahead of Milestone 1.

## Status legend
- **Proposed** — seeded; full text + acceptance in a later milestone.
- **Accepted** — decided and binding; changes require a superseding ADR.
- **Accepted (frozen)** — Accepted **and** part of the frozen provider architecture (extra change protocol).
- **Superseded** — replaced by a later ADR (linked).

## Index

| ADR | Title | Status | Written | Notes |
|-----|-------|--------|---------|-------|
| [ADR-001](ADR-001-rule-engine-primary.md) | Deterministic Rule Engine primary path, LLM as exception layer | Accepted | M1 (2026-07-19) | Master-prompt seed. |
| [ADR-002](ADR-002-two-llm-calls.md) | Two separate LLM calls (sentiment vs synthesis) | Accepted | M1 (2026-07-19) | Master-prompt seed. |
| [ADR-003](ADR-003-yaml-rules.md) | YAML rules instead of DB/vector store (with migration threshold) | Accepted | M1 (2026-07-19) | Master-prompt seed. |
| [ADR-004](ADR-004-replay-immutable-snapshots.md) | Replay Harness + immutable input snapshots as day-one requirement | Accepted | M1 (2026-07-19) | Referenced by ADR-007/011. |
| [ADR-005](ADR-005-regime-first-usd-irr-exception.md) | Regime-first analysis with USD/IRR low-sensitivity exception | Accepted | M1 (2026-07-19) | Master-prompt seed. |
| [ADR-006](ADR-006-storage-choice.md) | Storage technology choice (SQLite → Postgres path) | Accepted | M1 (2026-07-19) | Ties to challenge A1. |
| **[ADR-007](ADR-007-provider-agnostic-llm-gateway.md)** | **Provider-Agnostic LLM Gateway (MarketReasoner port + Adapter layer)** | **Accepted (frozen)** | **2026-07-18** | **Re-scoped from seed; folds in decision D4. FROZEN.** |
| [ADR-008](ADR-008-trader-signoff-gate.md) | Trader sign-off (`economic_rationale`) as a hard gate for rules | Accepted | M1 (2026-07-19) | Challenge A4. |
| [ADR-009](ADR-009-crypto-price-aggregation.md) | Multi-venue crypto price aggregation policy (median, deviation flags) | Accepted | M1 (2026-07-19) | Challenges A8/A9/A10. |
| [ADR-010](ADR-010-environments-secrets-deployment.md) | Environments, secrets, and deployment model | Accepted | M1 (2026-07-19) | Challenge A1. |
| **[ADR-011](ADR-011-degraded-run-failure-isolation.md)** | **Degraded Run & Provider Failure Isolation** | **Accepted (frozen)** | **2026-07-18** | **Split from ADR-007. FROZEN.** |
| [ADR-012](ADR-012-api-only-no-frontend.md) | API-only system, no front-end | Accepted | M1 (2026-07-19) | User directive; §3. |
| [ADR-013](ADR-013-evolution-extension-points.md) | Reserved extension points for the Evolution Roadmap | Accepted | M1 (2026-07-19) | §5 roadmap seams. |
| [ADR-014](ADR-014-summary-language-units-proxy-label.md) | Summary language (FA-only), USD/IRR units (IRT), proxy labeling (internal-only) | Accepted | pre-M2 (2026-07-19) | **Resolves O1/D1/D2.** |
| ADR-015 | *(reserved)* | — | — | Next free number for a future decision. |

## Milestone 1 authored ADRs

All master-prompt seed ADRs (001–006, 008, 009, 010) were **authored and Accepted in Milestone 1**, each
defending its decision to a skeptical principal engineer with Alternatives and Consequences. Two new ADRs were
added: **ADR-012** (API-only, no front-end — user directive) and **ADR-013** (reserved evolution extension
points). ADR-007 and ADR-011 were authored and frozen earlier (provider-independence freeze).

## Change protocol

- To change a frozen ADR (007, 011): write a new ADR that **supersedes** it; mark the old one `Superseded` with
  a link. Never edit an Accepted ADR's decision in place.
- Whenever a challenged assumption (product `00-decisions-and-open-items.md`) is accepted by the reviewer, it
  becomes (or updates) a numbered ADR here in the same milestone.
