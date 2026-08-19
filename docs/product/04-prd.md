# MVP Feature Specification (PRD)

> **Milestone 0 deliverable.** Features scoped **exactly** to master-prompt §2 — nothing more (§3 non-goals
> enforced). Each feature: rationale, the persona need it serves, acceptance criteria (linked to
> [03-use-cases.md](03-use-cases.md)), and out-of-scope notes. **No feature without a persona need.**
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

## Scope statement

Build the ten capabilities of §2 and **only** those. Every feature below traces to §2. Where a Milestone 0
challenge (A1–A11) or decision (D1–D3) refines a feature, it is noted inline. Non-goals (§3) are restated in
**§ Out of scope** at the end and are binding.

**Notation:** `F-#` feature ID (referenced by the traceability matrix and component design in M1). "Serves"
cites personas P1–P4. "AC" cites use-case acceptance criteria.

---

## F-1 — Scheduled pipeline + event-trigger path (§2.1)

**What:** A pipeline that runs **every 6 hours** (scheduled) and also on an **event-trigger path** for
CPI/FOMC/NFP-class releases, with **debounce/cooldown**: max one event Run per 30 minutes; concurrent events
aggregate into one Run.

**Rationale:** Freshness for P1's morning catch-up and P4's event-shock read; debounce prevents event storms
from producing redundant runs.

**Serves:** P1, P4. **AC:** UC-1, UC-2 (AC-2.1, AC-2.7).

**Acceptance criteria:**
- A scheduled Run is produced on each 6h tick and published ≤ 10 min after tick (SLO).
- An event Run is produced from a recorded Macro Event and published ≤ 5 min from trigger.
- Debounce enforces ≤ 1 event Run / 30 min; aggregated events recorded in `trigger_detail.debounced_events`.
- Idempotency: re-triggering an existing `run_id` is a no-op.

**Out of scope:** streaming, sub-6h scheduled cadence, autonomous re-runs, event *collection* (events are
entered manually — Q4).

---

## F-2 — Data ingestion (§2.2)

**What:** Ingest, per Run:
- Prices + multi-horizon changes (6h/24h/7d/30d) for all six assets.
- Technical Indicators: `rsi_14`, `macd_state`, `ema_20_50`, `atr_pct` (ATR normalized to % of price),
  `volume_ratio_20d`.
- Fear & Greed, BTC Dominance.
- Macro-event calendar with **consensus vs. actual → Surprise** (manual entry — Q4).
- Pre-collected News Items (external feed — Q3).

**Rationale:** The raw material for all deterministic features and the External LLM Provider calls.

**Serves:** P1, P3, P4. **AC:** UC-1 (AC-1.3), UC-2 (AC-2.3), UC-4.

**Feature-specific decisions (from M0 challenges):**
- **USD/IRR** sourced from internal kifpool API (`priceSellIRT`, USDT/IRT proxy), value in **Toman/IRT**
  (D1), single source of truth, 30–60 s cache, stale-fallback, behind a replaceable ingestor interface (Q1).
- **Fear & Greed** feeds **crypto assets only** (BTC/ETH/TOTAL_MCAP), not the Global Regime (challenge A6).
- **TOTAL_MCAP & BTC Dominance** are **index/context series** with a reduced indicator set (changes + trend +
  dominance shift), not the full technical suite (challenge A8).
- **BTC Dominance stablecoin methodology** fixed in config with rationale; cross-source deviation > 0.5 %
  **flags**, never silently averages (challenge A9 → ADR-009).
- Snapshot raw inputs **immutably** to the Event Log; mark stale/missing via `is_stale` / `data_gaps` instead
  of failing; run cross-source deviation checks.

**Acceptance criteria:**
- Each asset yields price + all four horizon changes, or a declared `data_gap`.
- Indicators computed per the asset's configured indicator set.
- Every ingested input is snapshotted immutably to the Event Log for replay (AC-6.1).
- Divergent sources are flagged, not averaged (AC per ADR-009).

**Out of scope:** news collection, live economic-calendar scraping, DXY/sekke inputs unless available (O2),
on-chain metrics (reserved slot only).

---

## F-3 — Deterministic scoring core (§2.3)

**What:** Compute **in code**: `trend_score`, `risk_score`, and `market_health_index` (MHI) as a **versioned
weighted projection** of the State Vector. Weights live in `config/weights/`, never in code or prompts.

**Rationale:** §7 "deterministic by default" and "honest weights" — all numbers are auditable and replayable.
Serves P3's reproducibility and P4's trust.

**Serves:** P1, P3, P4. **AC:** UC-1 (AC-1.3), UC-3 (AC-3.2), UC-6 (AC-6.2).

**Acceptance criteria:**
- `trend_score` ∈ [-1,1], `risk_score` ∈ [0,1], computed purely from indicators + event proximity.
- `market_health_index` ∈ [0,100] = configured weighted projection; changing weights = config change only.
- The External LLM Provider performs **no arithmetic**; scores are byte-reproducible on replay (AC-6.2).

**Out of scope:** provider-adjustable scores, learned weights (weights are static config in MVP).

---

## F-4 — Two separate LLM calls via a provider-agnostic Gateway (§2.4)

**What:** Two separate structured LLM jobs routed through the **LLM Gateway** (the project owns **no** model —
decision D4). **Call #1 (Sentiment):** conditionally scores only assets represented by a non-empty, fresh,
relevant weighted News Digest. **Call #2 (Synthesis):** human summaries, ordinal
Drivers, Novelty Flags, Data-Gap declarations. **Never merged** — separation prevents the sentiment score from
bending toward a nicer narrative.

**Rationale:** §2.4, ADR-002 (two calls), ADR-007 (provider-agnostic Gateway, re-scoped by D4). Serves P4
(unbiased sentiment) and P1 (clear explanation).

**Serves:** P1, P4. **AC:** UC-1 (AC-1.5), UC-3, UC-7 (AC-7.1–7.3).

**Provider-abstraction requirements (decision D4):**
- **Provider agnostic.** Both calls go through the `MarketReasoner` port → `LLMGateway`; the core has zero
  provider knowledge. Adding a provider = one new adapter, zero business-logic changes.
- **Runtime configuration.** `provider`, `model`, `temperature`, `timeout`, and retry/fallback order come from
  `config/models/providers.yaml`; changing provider requires **no code changes**.
- **Provider failover → Degraded Run.** On failure the Gateway tries the next configured provider; if **all**
  configured providers fail after retries, the Run continues as a **Degraded Run** (rule-engine-only, LLM
  fields absent, flagged + alert) — never a failed Run (see F-9 replay + UC-7).
- **Replay fidelity.** Each Run records `provider`, `model`, prompt hash, and the provider response so it
  replays reproducibly (adds `versions.provider`).

**Feature-specific decisions (from M0 challenges):**
- Self-consistency **double-call** is **config-gated, OFF by default**, reserved for high-surprise event runs
  (challenge A3).
- Grounding constraint on Call #2: the External LLM Provider may reference **only numbers present in the
  request**.
- Summary language: **Persian only** (`human_summary_fa`) — **resolved, ADR-014**. No EN field in v1.0.0.

**Acceptance criteria:**
- Two distinct jobs; Call #1 is skipped without eligible evidence, while Call #2 still runs from State Vector.
- No eligible news leaves affected assets at `sentiment=null` without marking the Run degraded or fabricating
  a Call Record/neutral score.
- All LLM calls flow through the Gateway; no core module imports a vendor SDK directly.
- Switching the configured provider/model is a config change only (no code diff).
- Structured-output enforcement on both calls (schema-validated).
- Call #2 introduces no numbers absent from its request (guardrail-checked).
- When all providers fail, a valid Degraded Run is still published (cross-ref F-9, UC-7).

**Out of scope:** owning/training/hosting a model; merged single-call reasoning; agentic/multi-turn behavior;
provider computing any deterministic score.

---

## F-5 — Rule Engine (§2.5)

**What:** Rules in **versioned YAML**, triggered by events/conditions; only **activated** Rules enter prompts.
Macro-event rules are defined on **Surprise**, not raw actuals. Every Rule carries `economic_rationale` and
`reviewed_by: senior_trader`.

**Rationale:** ADR-001 (deterministic primary path), ADR-008 (Trader sign-off gate). Serves P4's trust and
P1/P3's explainability.

**Serves:** P1, P3, P4. **AC:** UC-2 (AC-2.4–2.8), UC-3 (AC-3.3, AC-3.6).

**Feature-specific decisions (from M0 challenges):**
- Rules may carry **regime guards**; GOLD-on-hot-CPI must be regime-conditioned or `minor`+`uncertain`
  (challenge A4).
- Conflict handling (same asset, opposing effects) is deterministic and documented (M1/M3).

**Acceptance criteria:**
- A Rule with a Surprise-based condition activates iff the computed Surprise satisfies it.
- Activated Rules populate `activated_rules` + `causal_links`; unactivated Rules never enter prompts.
- **Hard gate:** a Rule missing `economic_rationale` or `reviewed_by: senior_trader` fails validation and
  cannot ship (ADR-008).

**Out of scope:** DB-backed rules (< 50 rules → YAML; ADR-003), vector retrieval, learned rules, hot-reload
(Phase 2).

---

## F-6 — News weighting in code (§2.6)

**What:** Eligible News Items satisfy deterministic relevance and freshness before
`effective_weight = source_quality × relevance × recency_decay` is computed. Freshness uses configured
`max_news_age_hours` (initially 36); weighting retains per-event-type half-lives.
The External LLM Provider **consumes** weights; it never assigns them.

**Rationale:** §7 "honest weights"; keeps sentiment inputs auditable. Serves P3, P4.

**Serves:** P3, P4 (indirectly P1 via better summaries). **AC:** UC-6 (ablation B isolates this).

**Acceptance criteria:**
- Effective weight computed deterministically per the formula; reproducible on replay.
- Half-lives are per-event-type config (`config/decay/`), versioned.
- Freshness is evaluated against injected Run time before coverage/global limiting; future, invalid, and
  over-age News Items are excluded in live and replay.
- The News Digest handed to Call #1 carries weights the External LLM Provider did not compute.

**Boundary:** News freshness is not event persistence. Persistent geopolitical/supply-crisis state is deferred
and must not be approximated by retaining stale News Items. MacroEvent/Rule lifetimes remain independent.

**Out of scope:** learned source reliability (Phase 3), entity extraction, news collection.

---

## F-7 — Regime-first flow with USD/IRR exception (§2.7)

**What:** Compute the **Global Regime first**, then analyze each asset in the Regime's context. **Exception:
USD/IRR** has `regime_sensitivity: low` and is analyzed on **domestic drivers**.

**Rationale:** ADR-005. Serves P1/P4 (correct market backdrop; realistic USD/IRR handling).

**Serves:** P1, P4. **AC:** UC-1 (AC-1.4), UC-4 (AC-4.3), UC-3 (AC-3.1, AC-3.4).

**Feature-specific decisions (from M0 challenges):**
- Regime is **mostly deterministic**; `regime.confidence` is a **deterministic** scalar (concordance +
  distance-to-boundary), never a fabricated or provider-supplied number (challenge A2).
- Global Regime uses **macro** inputs (surprises, risk_score, cross-asset), **not** crypto Fear & Greed
  (challenge A6).
- USD/IRR domestic drivers may include DXY / local gold-coin premium **if available** (challenge A7, O2);
  degrade to domestic news + trend otherwise.

**Acceptance criteria:**
- Regime classified before per-asset analysis; `previous_state`, `changed_this_run` correct vs. prior Run.
- USD/IRR analyzed on domestic drivers, unaffected by risk-on/off routing.
- `regime.confidence` is deterministic and documented.

**Out of scope:** provider-driven regime classification, regime prediction.

---

## F-8 — Output conforming to MarketStateRun Schema v1.0.0 (§2.8)

**What:** Every Run emits a `MarketStateRun` conforming to the frozen `market_state_run.v1.0.0.json`. Schema
changes only via an explicit schema-change section with rationale.

**Rationale:** P2's stable contract; P3's reproducibility.

**Serves:** P2 (primary), P1, P3, P4. **AC:** UC-1 (AC-1.1–1.4), UC-5 (all).

**Feature-specific decisions (from M0, all resolved — ADR-014):**
- Summary field: **`human_summary_fa` only** (Persian). No `human_summary_en` in v1.0.0.
- USD/IRR `price.currency = "IRT"` (Toman); **no Rial field / no `rial_multiplier`** in the contract.
- USDT/IRT proxy nature is **internal-only** — not surfaced in the payload (no `proxy_note` field).
- Reserved slots present: `expectation_context` (fed by surprises), `onchain_context` (`null` in MVP).

**Acceptance criteria:**
- 100 % of published Runs validate against the schema (contract tests).
- Reserved slots present and documented; `null` semantics specified.
- Golden fixtures (normal + degraded/stale) delivered in M2 and kept valid.

**Out of scope:** schema fields serving no persona need (flagged for removal in the traceability matrix).

---

## F-9 — Event Log + Replay Harness + Outcome Recorder (§2.9)

**What:** Every Run stores exact inputs, generated prompts (with hashes), config/**provider**/model/prompt
versions, and full output (including the provider response). A delayed job records realized Outcomes (6h/24h
returns vs. per-asset Noise Threshold, realized volatility). Any pipeline variant replays offline over full
history for paired comparison (ablations A–D).

**Rationale:** ADR-004 — replay + immutable snapshots are a **day-one** requirement; this is the product's
scientific backbone. Serves P3.

**Serves:** P3 (primary), P4. **AC:** UC-6 (all), UC-7.

**Feature-specific decisions (from M0 challenges):**
- Noise Threshold is **ATR-relative** (`k · ATR%`) with a floor, Trader-set per asset (challenge A5).

**Acceptance criteria:**
- Immutable input snapshots + prompt hashes + all versions on every Run.
- Deterministic-core replay is byte-identical on identical inputs+versions.
- Ablation variants A–D runnable offline; External LLM Provider calls mocked via fixtures in CI/replay.
- Outcomes attach +6h/+24h returns vs. Noise Threshold + realized volatility.

**Out of scope:** live-model replay, real-time outcome streaming.

---

## F-10 — Evaluation metrics (§2.10)

**What:** Directional accuracy vs. **two baselines** (persistence, always-neutral), **Brier score**,
**calibration buckets** by confidence — all **separated by `trigger_type`** (scheduled vs. event).

**Rationale:** P3's core job; the pre-registered decision rule for whether the synthesis role survives.

**Serves:** P3 (primary), P4. **AC:** UC-6 (AC-6.4, AC-6.6).

**Acceptance criteria:**
- Accuracy computed vs. persistence and always-neutral baselines.
- Brier + calibration buckets (0.5–0.6 … 0.9–1.0) with n per bucket.
- Scheduled and event Runs evaluated in **separate buckets**.
- Monthly report generated per the §11.6 structure; pre-registered decision-rule template present.

**Out of scope:** automated model retirement, live A/B in production (offline ablation only in MVP).

---

## Cross-cutting product requirements (bind all features)

| ID | Requirement | Source | Serves |
|----|-------------|--------|--------|
| X-1 | Every user-facing string frames output as **Observation, not advice**; banned terms enforced. | §6, dictionary | P1, P4, compliance |
| X-2 | `confidence` always labeled **"system confidence,"** never "probability." | §6 UX, A2 | P1, P3 |
| X-3 | `computed` vs `ordinal` weights are **visually distinct** in UI (contract requirement). | §6 UX | P1 |
| X-4 | Stale prices **dimmed** with a stale note. | §6 UX | P1 |
| X-5 | Disclaimer present in **API response metadata and UI**. | §6 compliance | P2, compliance |
| X-6 | `human_summary_fa` follows the style guide (describe/explain, never advise). | §6 UX | P1, P4 |

(Full UX/content spec: [06-ux-content-requirements.md](06-ux-content-requirements.md); compliance:
[07-compliance.md](07-compliance.md).)

---

## Out of scope for the MVP (§3 non-goals — binding)

- **No** price prediction, buy/sell recommendations, or portfolio logic.
- **No** agentic/autonomous LLM behavior — the configured External LLM Provider is a pure structured function.
- **No** owned/trained/hosted model — all LLM calls go through the provider-agnostic LLM Gateway to a
  configured external provider (decision D4).
- **No** vector DB / RAG; rules stay YAML until ~50 rules (ADR-003).
- **No** causal-inference engine — the causal graph is a **presentation artifact** from rule edges.
- **No** real Expectation Layer — `expectation_context` slot fed by surprises only.
- **No** on-chain analytics — `onchain_context` slot reserved, `null` in MVP.
- **No** UI implementation — we own the JSON contract + a mock-serving endpoint.
- **No** user accounts, auth beyond a static API key, multi-tenancy, streaming, or horizontal scaling.
- **No** news collection or live economic-calendar scraping — external feed (Q3) + manual events (Q4).

## Feature → §2 coverage check

| §2 item | Feature | §2 item | Feature |
|---------|---------|---------|---------|
| 2.1 scheduled + event | F-1 | 2.6 news weighting | F-6 |
| 2.2 ingestion | F-2 | 2.7 regime-first | F-7 |
| 2.3 scoring core | F-3 | 2.8 schema output | F-8 |
| 2.4 two LLM calls | F-4 | 2.9 log/replay/outcome | F-9 |
| 2.5 rule engine | F-5 | 2.10 evaluation | F-10 |

All ten §2 items covered; no feature outside §2.
