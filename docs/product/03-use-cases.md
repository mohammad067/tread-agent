# Use Cases & User Stories with Acceptance Criteria

> **Milestone 0 deliverable.** Each use case: story, flow, and **acceptance criteria that are individually
> traceable** to a planned automated test (`T-xxx`) or an explicit **manual-test note** (`M-xxx`).
> Test IDs are placeholders resolved to real tests in Milestones 3–6; the traceability obligation is binding
> now. Terms per [09-domain-dictionary.md](09-domain-dictionary.md); personas per
> [02-personas.md](02-personas.md).
> **Version:** 0.1.0

**Legend for the "Verified by" column:** `T-###` = automated test (unit/contract/golden/replay/integration);
`M-###` = manual-test note (documented human check where automation isn't meaningful at MVP).

---

## UC-1 — Morning catch-up (P1 Analyst)

> **Story:** As a dashboard analyst, I open the app at the start of my day and want a current, trustworthy
> read on every asset and the overall Regime, so I can orient in under a minute.

**Main flow:** Analyst requests latest state → dashboard calls `GET /v1/state/latest` → renders Regime banner,
six asset cards (score, MHI, summary), freshness indicators.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-1.1 | `GET /v1/state/latest` returns the most recent MarketStateRun wrapped in the `meta` envelope with `api_version`, `next_scheduled_run`, `disclaimer`. | T-101 (contract) |
| AC-1.2 | The response validates against `market_state_run.v1.0.0.json`. | T-102 (contract) |
| AC-1.3 | All six assets (BTC, ETH, GOLD, WTI, USD_IRR, TOTAL_MCAP) are present, each with `scores` and `market_health_index`. | T-103 (contract) |
| AC-1.4 | `regime.state` ∈ {risk_on, risk_off, transition, event_driven} and `regime.changed_this_run` is boolean. | T-104 (contract) |
| AC-1.5 | Each asset carries a non-empty `human_summary_fa` (Persian only, ADR-014) describing—not advising. | T-105 (golden) + M-105 (Trader realism review) |
| AC-1.6 | Response is served with API p95 ≤ 300 ms for the latest-state endpoint. | T-106 (perf smoke, M5) |

---

## UC-2 — Event-shock moment (P1 Analyst, P4 Trader)

> **Story:** As an analyst/trader, when a CPI-class surprise prints, I want an updated Market State that
> explains the cross-asset impact **within minutes**, tied to a named Rule with an economic rationale.

**Main flow:** Macro event recorded (consensus+actual) → Surprise computed → event listener fires (debounced)
→ event Run executes → new MarketStateRun published with `trigger_type: event`, activated Rules, causal links.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-2.1 | An event Run is published **≤ 5 minutes** from trigger. | T-201 (integration, M5) + M-201 |
| AC-2.2 | The Run's `trigger_type` = `event` and `trigger_detail` names the `event_id` and `debounced_events` count. | T-202 (contract) |
| AC-2.3 | Surprise is computed deterministically as `actual − consensus` in event-natural units and stored. | T-203 (unit) |
| AC-2.4 | Rules trigger on **Surprise**, not raw actuals: a rule with `condition: surprise_core_mom >= 0.1` activates iff the computed surprise meets it. | T-204 (unit, rule matcher) |
| AC-2.5 | Each activated Rule appears in the affected assets' `activated_rules` with `strength`, `horizon`, `decay_remaining`, and yields a `causal_links` edge with `via_rule`. | T-205 (unit + contract) |
| AC-2.6 | Every activated Rule carries a non-empty `economic_rationale` and `reviewed_by: senior_trader`. | T-206 (rule schema validation) + M-206 (Trader sign-off gate) |
| AC-2.7 | Multiple events within the 30-min cooldown aggregate into one Run (`debounced_events > 0`), not multiple runs. | T-207 (unit, debounce) |
| AC-2.8 | GOLD's CPI effect is **not** unconditional bearish: the rule is regime-guarded or downgraded to `minor`+`uncertain` (challenge A4). | T-208 (rule unit) + M-208 (Trader review) |

---

## UC-3 — "Why did the state change?" drill-down (P1 Analyst, P4 Trader)

> **Story:** As an analyst, when the Regime or an asset's condition changes, I want to see the drivers and the
> causal chain, so I can understand and explain the change.

**Main flow:** Analyst opens an asset/regime detail → dashboard renders `drivers` (with weight types),
`causal_links`, and `activated_rules` for the current Run; optionally compares to the previous Run.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-3.1 | `regime.drivers` lists drivers each with a `weight_type` of `computed` (real %) or `ordinal` (level). | T-301 (contract) |
| AC-3.2 | `computed` weights are real percentages from the scoring formula; `ordinal` drivers carry `level` ∈ {dominant, major, moderate, minor} and **no fabricated percentage**. | T-302 (unit + contract) |
| AC-3.3 | Each `causal_links` edge references an existing `via_rule` present in some asset's `activated_rules`. | T-303 (contract cross-check) |
| AC-3.4 | `regime.previous_state` and `changed_this_run` correctly reflect the prior Run's regime. | T-304 (unit, sequence) |
| AC-3.5 | A `GET /v1/runs/{run_id}` on the prior Run returns the earlier state for comparison. | T-305 (contract) |
| AC-3.6 | The causal graph is assembled **only** from activated-rule edges (no provider-invented edges). | T-306 (unit, guardrail) |

---

## UC-4 — Stale-data situation: USD/IRR on a Tehran holiday (P1 Analyst, P4 Trader)

> **Story:** As an analyst, when the Tehran market is closed, I want USD/IRR clearly marked stale with the
> last valid price and an honest data-gap note, so I'm not misled.

**Main flow:** kifpool API unavailable or market closed → ingestor reuses last successful value → price flagged
`is_stale` with a reason → `data_gaps` records exclusions → analysis proceeds degraded, not failed.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-4.1 | When the source is unavailable, USD_IRR uses the last successful value with `is_stale: true` and a `stale_reason`. | T-401 (unit, ingestor) |
| AC-4.2 | Informal overnight quotes are **excluded** from computation and declared in `data_gaps` (e.g., `informal_overnight_quotes_excluded`). | T-402 (unit) + M-402 |
| AC-4.3 | USD_IRR carries `regime_sensitivity: low` and is analyzed on domestic drivers, not the Global Regime. | T-403 (unit, regime routing) |
| AC-4.4 | A stale asset never fails the Run; the Run still publishes for all other assets. | T-404 (unit, degrade-not-fail) |
| AC-4.5 | The USD_IRR value is expressed in the documented unit (IRT/Toman) with `currency` set accordingly (decision D1). | T-405 (contract) + M-405 |
| AC-4.6 | USD_IRR is presented plainly with `currency: "IRT"`; the USDT/IRT proxy nature is **internal-only**, not surfaced in the payload (ADR-014). | M-406 (doc check) |

---

## UC-5 — Developer contract consumption (P2 Developer)

> **Story:** As a developer, I want to integrate the JSON contract and endpoints from documentation alone,
> including knowing the shape of degraded/stale runs, so I can build without reverse-engineering.

**Main flow:** Developer reads schema + traceability matrix + golden fixtures → codes against endpoints →
handles `null` reserved slots and stale/degraded variants.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-5.1 | Golden sample fixtures exist for a normal run **and** a degraded/stale run, both schema-valid. | T-501 (golden + contract) |
| AC-5.2 | Reserved slots `expectation_context` (populated by surprises) and `onchain_context` (`null` in MVP) are documented and present in the schema. | T-502 (contract) |
| AC-5.3 | Every schema field maps to a documented need in the traceability matrix; unmapped fields are flagged. | M-503 (matrix review) |
| AC-5.4 | `GET /v1/runs?from=&to=&trigger_type=` filters by range and Trigger Type. | T-504 (contract) |
| AC-5.5 | Schema/version changes are announced per the release policy with deprecation windows. | M-505 (policy adherence) |
| AC-5.6 | `GET /v1/health` returns liveness and the `next_scheduled_run`. | T-506 (contract) |

---

## UC-6 — Scientific evaluation & replay (P3 Evaluator)

> **Story:** As a quant, I want to replay ablation variants over stored history and get paired accuracy/Brier
> comparisons separated by Trigger Type, so I can judge whether each component earns its keep.

**Main flow:** Evaluator selects a date range + variant (A–D) → Replay Harness re-runs on immutable input
snapshots → Outcome records supply realized results → metrics report generated.

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-6.1 | Every Run persists its exact inputs, generated prompts with hashes, the provider response, and all versions (rulebook, weights, prompts, **provider**, model, pipeline). | T-601 (integration) |
| AC-6.2 | The Replay Harness reproduces a stored Run's output **byte-identically** for the deterministic core on identical inputs + versions. | T-602 (replay regression) |
| AC-6.3 | Ablation variants A (rules-only), B (+deterministic-news), C (+LLM-sentiment), D (full) are each runnable offline. | T-603 (replay) |
| AC-6.4 | Metrics report directional accuracy vs. **persistence** and **always-neutral** baselines, Brier score, and calibration buckets — **separated by `trigger_type`**. | T-604 (unit, metrics) |
| AC-6.5 | Outcomes attach realized +6h/+24h returns vs. per-asset Noise Threshold (ATR-relative) and realized volatility. | T-605 (unit, outcome recorder) |
| AC-6.6 | A pre-registered decision-rule template exists ("if variant D doesn't beat B by X Brier in 3 months, remove synthesis"). | M-606 (doc check) |
| AC-6.7 | External LLM Provider calls are mocked in CI via recorded fixtures; replay never calls a live provider. | T-607 (CI config) |

---

## UC-7 — Degraded run: provider failover exhausted (P3 Evaluator, P1 Analyst) — reliability

> **Story:** As an operator/analyst, when the configured External LLM Provider(s) fail, I still want a
> published Market State from the deterministic Rule Engine with an alert, so the product degrades gracefully.

**Main flow:** Call to the configured External LLM Provider fails → LLM Gateway retries, then **fails over to
the next configured provider** → if **all** configured providers fail, the pipeline continues and emits a
**Degraded Run** (rule-engine-only) with a degradation flag and an alert. The deterministic core is never
blocked by an external provider (decision D4).

| # | Acceptance criterion | Verified by |
|---|----------------------|-------------|
| AC-7.1 | On provider failure after the retry policy, the LLM Gateway fails over to the next configured provider before degrading. | T-701a (unit, failover) |
| AC-7.2 | When **all** configured providers fail, the Run publishes a rule-engine-only **Degraded Run** rather than failing. | T-701b (unit, degrade-not-fail) |
| AC-7.3 | The Degraded Run is clearly flagged (degradation/guardrail flag) and an alert is emitted. | T-702 (unit) + M-702 |
| AC-7.4 | Sentiment and other LLM-generated fields absent from a Degraded Run are represented explicitly (not fabricated zeros passed off as scores). | T-703 (contract/guardrail) |
| AC-7.5 | Switching the configured provider/model (`config/models/providers.yaml`) changes behavior with **no code change**. | T-704a (config-driven) + M-704 |
| AC-7.6 | Guardrails run deterministic post-validation (schema, ranges, consistency, contradiction summary-vs-scores) on every Run, degraded or not. | T-704b (property tests) |

---

## Traceability summary

- **Every** acceptance criterion above cites at least one `T-###` or `M-###`. This satisfies the master
  prompt's rule: *every acceptance criterion must be traceable to at least one automated test or an explicit
  manual-test note.*
- The `T-###`/`M-###` IDs are placeholders in Milestone 0; Milestones 3–6 bind them to concrete tests and
  this file's right-hand column is updated in lockstep (PRD-vs-implementation divergence is a defect, §8).
- Manual-test notes concentrate where realism/judgment matters (Trader review, doc checks) or where MVP
  automation isn't cost-justified (sub-5-min latency wall-clock).
