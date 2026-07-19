# Evolution Roadmap, Traceability & Implementation Plan

> **Milestone 1.** The seven-phase evolution roadmap with named extension points, the PRD-feature →
> component/ADR traceability matrix, the milestone-by-milestone implementation plan, and the **Open Questions**.
> **Design only.** Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> Extension-point policy: [../adr/ADR-013-evolution-extension-points.md](../adr/ADR-013-evolution-extension-points.md).
> **Version:** 1.0.0

---

## 1. Evolution Roadmap (Phases 1–7)

**Rule (ADR-013):** every phase names the **existing extension point** that absorbs it and which current
components **survive unchanged**. No phase may require a ground-up redesign.

| Phase | Name | Absorbed by (extension point) | Current components that survive unchanged |
|-------|------|-------------------------------|-------------------------------------------|
| **1** | **Static Rule Engine (this MVP)** | — | — (baseline) |
| **2** | Dynamic Rules (DB, hot-reload, rule analytics) | **Rule store interface** (RuleEngine reads via a loader; YAML→SQL past ~50 rules, ADR-003) | FeatureEngine, ScoringEngine, RegimeClassifier, Guardrails, Pipeline, API, Reasoning layer |
| **3** | Deep News Understanding + **On-chain Context** | **`onchain_context` slot** + **`MarketReasoner` port** (richer NLU behind same port) + Source port (on-chain ingestors) | Deterministic core, scoring, regime, rules, replay, API contract (additive) |
| **4** | Expectation Layer (per-asset; USD/IRR has no derivatives data) | **`expectation_context` slot** (surprise-fed today → real implied-vol/basis/positioning later) | Everything else; USD/IRR explicitly excluded from derivatives |
| **5** | Portfolio Intelligence | **New layer above** the Market State (consumes the JSON contract) | The entire engine (unchanged; new layer sits on top) |
| **6** | Recommendation Engine | **Recommendation layer boundary** — a separate layer **above** Market State, never inside it | The entire engine; compliance boundary preserved (engine still observation-only) |
| **7** | Autonomous Market Intelligence | Orchestration above the engine + existing ports | Deterministic core + provider abstraction unchanged |

**Reserved today (zero implementation):** `expectation_context`, `onchain_context`, confidence-calibration hook
(Platt scaling), rule-store interface (SQL migration), `MarketReasoner` port, source port, recommendation-layer
boundary. Confidence stays **system confidence** until Phase-level calibration is added; the calibration seam
exists now (ADR-013).

**Why this satisfies "no ground-up redesign":** the two hardest-to-change things — the **frozen provider
boundary** (ADR-007) and the **immutable Event Log / replay** (ADR-004) — are exactly the ones every later
phase builds *on*, not *around*. New capability enters as a new adapter, a new ingestor, a filled schema slot,
or a layer above — never as a rewrite of the core.

---

## 2. PRD feature → component / ADR traceability

Every PRD feature (F-1…F-10, [../product/04-prd.md](../product/04-prd.md)) maps to the components that realize
it and the ADRs that govern it. This is the "every component traces to a PRD feature" check (§9 M1).

| Feature | Primary components | Governing ADRs | M1 doc |
|---------|--------------------|----------------|--------|
| **F-1** Scheduled + event pipeline (debounce) | Scheduler, Event Trigger, Orchestrator | ADR-010 | pipelines §1 |
| **F-2** Data ingestion | Ingestors (PriceSource incl. kifpool, FearGreed[crypto], Dominance, News, Event), FeatureEngine (inputs) | ADR-009 | module-catalog C, pipelines §3 |
| **F-3** Deterministic scoring core | FeatureEngine, ScoringEngine, RegimeClassifier | ADR-001, ADR-005 | module-catalog A2/A5 |
| **F-4** Two LLM calls via Gateway | MarketReasoner, LLMGateway, PromptBuilder, Adapters | ADR-002, **ADR-007**, **ADR-011** | llm-architecture-m1 |
| **F-5** Rule Engine | RuleEngine (loader/matcher/conflict) | ADR-001, **ADR-003**, **ADR-008** | pipelines §4 |
| **F-6** News weighting in code | NewsWeigher | ADR-001 | pipelines §3 |
| **F-7** Regime-first + USD/IRR exception | RegimeClassifier, ScoringEngine | **ADR-005** | module-catalog A5 |
| **F-8** Schema-conformant output | core DTOs, Guardrails, Persistence, API | ADR-012, release policy | database, api-design |
| **F-9** Event Log + Replay + Outcome | Event Log, ReplayHarness, OutcomeRecorder, Call Records | **ADR-004**, ADR-007 | database, pipelines §5/§7 |
| **F-10** Evaluation metrics | Evaluation (metrics, ablation, reports) | ADR-004 | pipelines §6 |

**Reverse check (every major component traces to a feature):** Scheduler→F-1; Ingestors→F-2; FeatureEngine→
F-3; ScoringEngine/Regime→F-3/F-7; RuleEngine→F-5; NewsWeigher→F-6; Reasoning stack→F-4; Guardrails→F-8;
Persistence/Event Log→F-8/F-9; Evaluation→F-9/F-10; API→F-8. **No orphan components.**

---

## 3. Milestone-by-milestone implementation plan

> Reaffirms master-prompt §9 with M1 architecture bound in. **Each milestone stops for your approval.** Code
> begins only at Milestone 3.

| Milestone | Deliverables (design → code boundary) | Gates / CI |
|-----------|----------------------------------------|-----------|
| **M0 Product Foundation** ✅ | Full §6 product docs, challenged assumptions, decisions | — |
| **Freeze (pre-M1)** ✅ | ADR-007, ADR-011, frozen provider spec | — |
| **M1 Architecture** ◀ *this* | Overview, module catalog, DB, API, pipelines, LLM, cross-cutting, deployment, sequences, ADR-001…013, roadmap, plan | **No code** |
| **M2 Contracts & Schemas** | `market_state_run.v1.0.0.json` + internal DTO schemas; OpenAPI; config file designs; DB schema + migrations; versioning; **golden fixtures** (normal + degraded). **O1/D1/D2 resolved (ADR-014).** | Schema/contract tests; **schema files & migrations only** |
| **M3 Deterministic Core** | Ingestion interfaces + mocks; FeatureEngine; RuleEngine (schema+matcher+tests); NewsWeigher; ScoringEngine; RegimeClassifier; Guardrails. | **CI live**: ruff, mypy --strict, unit, contract, golden, coverage ≥90%, import-boundary lint |
| **M4 LLM Layer** | ReasoningRequest/Response; MarketReasoner; **LLMGateway + Router + Health + CircuitBreaker**; ≥1 real ProviderAdapter + test doubles; PromptBuilder (versioned/hashed); structured-output enforcement; self-consistency (off by default). | LLM mocked via fixtures; golden prompt tests |
| **M5 Pipeline & Persistence** | Scheduler + event trigger + debounce; end-to-end lifecycle; Event Log + immutable snapshots + Call Records; API endpoints; error handling; **Degraded Run** path; Docker; (Postgres, rate-limit begin here). | Integration tests; degraded-run test |
| **M6 Evaluation & Replay** | OutcomeRecorder; ReplayHarness; ablation A–D; metrics (accuracy vs baselines, Brier, calibration) separated by trigger_type; monthly report; pre-registered decision rule. | Replay regression (nightly); metrics tests |
| **M7 Hardening & Bible** | Observability dashboards; runbook; model-migration playbook; DR rehearsal; acceptance sweep vs M0 PRD; **PROJECT_BIBLE** (generated). | Full gate + DR rehearsal |

**Dependency ordering rationale:** contracts (M2) precede code (M3) so every module builds against frozen
schemas; the deterministic core (M3) precedes the LLM layer (M4) so ablation variant A (rules-only) is
runnable before any provider exists; persistence + pipeline (M5) precede evaluation (M6) because evaluation
reads the Event Log. The frozen provider boundary (ADR-007) means M4 can add providers without touching M3.

---

## 4. Consistency check against Milestone 0 (contract compatibility)

| M0 artifact | M1 conformance |
|-------------|----------------|
| Traceability Matrix | §2 above maps every feature→component; schema fields unchanged (M2 reconciles). |
| UX Requirements | Preserved as **consumer obligations** (ADR-012; api-design §10). |
| Compliance | Observation-only enforced in prompts + guardrails + API; disclaimer in envelope. |
| KPI Tree | Metric emission points fixed in cross-cutting §4; product vs model families kept separate. |
| Domain Dictionary | All component/field/endpoint names use dictionary terms (v0.3.0). |
| Release Policy | Independent versioning of schema/rulebook/weights/prompts/provider/model/pipeline recorded per run. |
| JSON Schema (frozen contract) | No change proposed in M1; schema realized in M2. **O1/D1/D2 resolved (ADR-014): FA-only summary, IRT units, proxy internal-only.** |

**No Milestone 0 decision is violated by this architecture.**

---

## 5. Open Questions

> Per your instruction: **nothing guessed.** Each item is recorded with its impact and a working default where
> one exists. Blocking items are marked. None blocks *reviewing* M1; the marked ones block **M2 (contracts)**.

| # | Open question | Impact | Default (if any) | Blocks |
|---|---------------|--------|------------------|--------|
| ~~O1~~ | ✅ **RESOLVED (ADR-014): Persian-only** `human_summary_fa`; no EN in v1.0.0. | — | — | closed |
| ~~D1~~ | ✅ **RESOLVED (ADR-014): IRT (Toman)**; `currency:"IRT"`; no Rial field / no `rial_multiplier`. | — | — | closed |
| ~~D2~~ | ✅ **RESOLVED (ADR-014): proxy internal-only**, not surfaced; no `proxy_note` field. | — | — | closed |
| **OQ-3** | Rule **conflict-resolution** policy (same asset, opposing effects): higher-strength-wins vs net/attenuate vs flag-only? | RuleEngine matcher semantics | *none — needs Trader ruling* | M3 RuleEngine |
| **OQ-4** | Regime-guarded rule **evaluation split** (phase-1 pre-scoring vs phase-2 post-regime): confirm the exact rule categories in each phase. | Pipeline stage ordering | two-phase as described (pipelines §2) | M3 pipeline |
| **OQ-5** | Crypto **venue list** + BTC Dominance **stablecoin methodology** (which aggregator, incl/excl stablecoins)? | ADR-009 config values | *none — Blockchain persona ruling* | M2 config / M3 ingestion |
| **OQ-6** | **Relevance** signal for `effective_weight` (how is news→asset relevance scored deterministically?) | NewsWeigher formula input | *none — needs definition* | M3 NewsWeigher |
| **OQ-7** | LLM **provider + model** for the first real adapter, and **monthly USD budget**. | providers.yaml, cost alerts | Claude first adapter; budget TBD | M4 |
| **OQ-8** | Confirm **`error-handling.md` split** vs folded into `cross-cutting.md` (minor doc-org). | doc structure | folded | cosmetic |
| **OQ-9** | ATR-relative **noise-threshold `k`** per asset (Trader-set constants). | OutcomeRecorder labeling | *none — Trader ruling* | M6 evaluation |
| **OQ-10** | Event set beyond CPI/FOMC/NFP (PCE/ECB)? | event types config | CPI/FOMC/NFP for MVP (D3) | M2 config |

**Items needing a human ruling (not defaultable):** OQ-3, OQ-5, OQ-6, OQ-9 (Trader/Blockchain persona
decisions). **O1/D1/D2 are now resolved and frozen (ADR-014)** — removed from the blocking set. I will **not**
guess the remaining OQ items; they are surfaced here and will gate the milestones noted.
