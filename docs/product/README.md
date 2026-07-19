# Product Documentation — Market State Engine

> **Milestone 0 — Product Foundation.** This directory is the complete §6 product documentation set. It is a
> first-class, versioned deliverable, kept in lockstep with technical documentation (§8). No code or
> architecture is defined here — those begin at Milestone 1 (pending your approval).

## Read in this order

| # | Document | Purpose |
|---|----------|---------|
| 00 | [Decisions & Open Items](00-decisions-and-open-items.md) | Challenged assumptions, answered/open questions, decision log. **Start here.** |
| 09 | [Domain Dictionary](09-domain-dictionary.md) | Ubiquitous language — **binding** exact terms for all docs/code. |
| 01 | [Vision & Positioning](01-vision.md) | The problem, the wedge, what this is *not*. |
| 02 | [Personas & JTBD](02-personas.md) | P1 Analyst, P2 Developer, P3 Evaluator, P4 Trader. |
| 03 | [Use Cases](03-use-cases.md) | User stories + acceptance criteria traced to tests. |
| 04 | [PRD](04-prd.md) | MVP features F-1…F-10 scoped exactly to §2. |
| 05 | [Traceability Matrix](05-traceability-matrix.md) | Every schema field → user need. |
| 06 | [UX & Content Requirements](06-ux-content-requirements.md) | UI contract + `human_summary_fa` style guide. |
| 07 | [Compliance](07-compliance.md) | Observation-not-advice framing + disclaimer placement. |
| 08 | [KPI Tree](08-kpi-tree.md) | Product KPIs vs. model-quality metrics. |
| 10 | [Release Policy](10-release-policy.md) | Changelog, versioning, deprecation. |

## Cross-cutting invariants (established in Milestone 0)

- **Ubiquitous language is binding.** Every identifier/field/path/log/doc uses the Domain Dictionary terms.
- **No owned model; provider-agnostic (D4).** We own no LLM. All LLM calls flow through a provider-agnostic
  **LLM Gateway** to a configured External LLM Provider (OpenAI/Claude/Gemini/DeepSeek/Grok/future), swappable
  by config. If all providers fail, the deterministic core still emits a valid Market State (Degraded Run).
- **Observation, not advice.** Enforced across External LLM Provider prompts, guardrails, and UX.
- **Honest weights & confidence.** `computed` %s vs `ordinal` levels; `confidence` = system confidence.
- **Everything replayable.** The Event Log and per-run versioning are day-one, non-negotiable.
- **No feature without a persona need; no schema field without a served need.**

## Open items status

- ✅ **O1 — summary language:** RESOLVED — **Persian only** (`human_summary_fa`). [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md)
- ✅ **D1 — USD/IRR units:** RESOLVED — **IRT (Toman)**; no Rial field. [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md)
- ✅ **D2 — USDT proxy labeling:** RESOLVED — **internal-only**, not surfaced in API/UI. [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md)
- **O3 — LLM provider + budget**, **O4 — jurisdiction**, **O5 — deployment host**: later milestones (non-blocking).

All schema-blocking items are closed; **Milestone 2 (Contracts & Schemas) may proceed.**

See [00-decisions-and-open-items.md](00-decisions-and-open-items.md) for the full list and defaults.
