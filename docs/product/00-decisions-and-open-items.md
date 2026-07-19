# Milestone 0 — Decisions, Challenged Assumptions & Open Items

> **Status:** Milestone 0 (Product Foundation). No code, no architecture.
> **Purpose:** Record (a) assumptions challenged before designing, (b) answered clarifying questions,
> (c) still-open questions carried into the docs with explicit defaults, and (d) new decisions surfaced
> during Milestone 0. Every accepted challenge becomes an ADR in Milestone 1.

---

## 1. Answered clarifying questions (locked)

| # | Question | Answer (binding) | Downstream impact |
|---|----------|------------------|-------------------|
| Q1 | USD/IRR data source | **Internal `kifpool` REST API.** Endpoint `https://api.kifpool.app/api/spot/price?symbol=USDT&format=json`; use `priceSellIRT` (USDT sell price) as the USD/IRR reference; **USDT is the USD proxy**; value is in **Toman (IRT), not Rial**; single source of truth; cache 30–60 s; on outage reuse last value marked `is_stale`; provider hidden behind a replaceable interface. | Defines the `USD_IRR` ingestor contract; forces a Toman↔Rial unit decision (D1); introduces a USDT-depeg integrity caveat (D2). |
| Q2 | Summary language | ✅ **RESOLVED (ADR-014): Persian only (`human_summary_fa`).** (Was carried as O1; the reviewer's final decision is FA-only, EN removed from MVP.) | Was blocking schema freeze — now closed. |
| Q3 | News source | **External pre-collected feed.** MVP only *consumes* news via a `NewsItem` contract; collection is out of MVP scope. | Defines `NewsItem` input contract; NewsWeigher operates on supplied items only. |
| Q4 | Macro-event calendar | **Manual entry.** Consensus + actual recorded by hand (or a tiny loader) for the handful of CPI/FOMC/NFP-class events per month; surprise computed deterministically. | Defines `MacroEvent` input contract; event-trigger path is fed by curated entries, not a live scrape. |

---

## 2. Challenged assumptions (propose → wait → proceed)

Each challenge below is a proposal, not a silent deviation. Items marked **→ ADR** become numbered ADRs
in Milestone 1 if you accept them. Items marked **→ PRD** are scope decisions folded into `04-prd.md`.

### Principal Software Architect

**A1 — Enterprise-ops surface (§12) vs. "no over-engineering" (§7).**
The MVP runs ~4 scheduled runs/day over 6 assets, yet §12 mandates Postgres + compose, DR rehearsal,
99.5% availability, public-API rate limiting, and nightly replay CI. **Proposal:** keep every extension
point and the **event log** (non-negotiable — it is the product's replay backbone), but **stage** the heavy
ops. MVP core (M3–M5) ships on **SQLite + single container** with lint/type/unit/contract/golden CI;
**Postgres, DR rehearsal, and the rate limiter move to M5/M7** as explicit productionization steps. Honors
"simpler when equal" without losing auditability. **→ ADR-006 (storage) and ADR-010 (deployment).**

### AI Systems Architect

**A2 — `regime.confidence` presented as a number while regime is "mostly deterministic."**
If regime classification is deterministic, its confidence must also be a deterministic function or it is a
fabricated number (which §7 "Honest weights" forbids). **Proposal:** define `regime.confidence` as a
**deterministic scalar** from driver concordance + distance-to-classification-boundary. No LLM involvement.
Documented in the Domain Dictionary and the RegimeClassifier spec. **→ PRD + Domain Dictionary.**

**A3 — Self-consistency double-call doubles the most-frequent LLM cost for marginal MVP value.**
The sentiment call runs every run; double-calling it is the single largest recurring cost. **Proposal:**
make double-call **config-gated and OFF by default in MVP**; reserve it as a tunable enabled for
**high-surprise event runs only**. Keeps the capability, defers the cost. **→ PRD (config), ADR-007 note.**

### Senior Trader

**A4 — Sample rule marks GOLD bearish on hot CPI unconditionally — a desk would laugh.**
Gold's CPI reaction is regime-dependent: bearish when hot CPI → real-yields-up (hiking regime), but
repeatedly **bullish** under fiscal-dominance / de-dollarization / cutting-cycle regimes. **Proposal:**
gold's CPI effect must be **conditioned on the rate-cycle regime**, or downgraded to `minor` + `uncertain`,
never unconditional `moderate`. Encoded as a rule-authoring constraint (rules may carry regime guards).
**→ PRD (Rule Engine acceptance criteria); Trader sign-off gate ADR-008.**

**A5 — Fixed noise thresholds mislabel ordinary volatility as signal.**
BTC ±1.5% at 24h sits **inside** normal daily noise (BTC 24h realized vol is frequently 2–4%). A fixed band
makes the Outcome Recorder call ordinary chop "signal." **Proposal:** express per-asset noise bands as
**ATR-relative** (`k · ATR%`) with a fixed floor, so the outcome classifier adapts to the volatility regime;
Trader sets `k` per asset. **→ PRD (Outcome Recorder); asset config schema.**

**A6 — Fear & Greed is a crypto sentiment index, not a macro-regime input.**
alternative.me F&G measures crypto positioning; feeding it into a Global Regime that also governs
Gold/WTI/USD-IRR conflates crypto sentiment with macro. **Proposal:** F&G feeds **BTC/ETH/TOTAL_MCAP
context only**; the Global Regime uses macro inputs (surprises, risk_score, cross-asset). **→ PRD + regime spec.**

**A7 — USD/IRR is "low regime sensitivity" but NOT insensitive to USD strength and gold.**
The Tehran parallel rate tracks DXY and the domestic gold-coin (sekke) premium closely. **Proposal:**
USD/IRR's domestic driver set explicitly includes **DXY and local gold/coin premium**, not just "domestic
news." Low *global-risk* sensitivity ≠ no external drivers. **→ PRD (USD/IRR rules) — note: DXY/sekke are
data inputs deferred if unavailable in MVP; see O2.**

### Senior Blockchain Engineer

**A8 — TOTAL_MCAP treated as a full technical asset double-counts BTC.**
Total market cap is BTC-dominated; its RSI/MACD/EMA largely re-encode BTC's. **Proposal:** TOTAL_MCAP and
BTC Dominance are **index/context series** with a reduced indicator set (multi-horizon changes + trend +
dominance shift), not the full per-asset technical suite. **→ PRD + asset config (index-class assets).**

**A9 — Dominance / stablecoin methodology must be pinned now, not "later."**
BTC Dominance flips meaning depending on whether stablecoins are in the denominator. **Proposal:** MVP fixes
**one aggregator methodology** in `config/sources/` (state which, with rationale), and cross-source
deviation > 0.5 % **flags** rather than silently averages. **→ ADR-009.**

**A10 — Crypto price integrity: USDT-as-USD proxy for USD/IRR inherits stablecoin risk.**
See D2 below. **→ ADR-009 scope note.**

### Product Manager

**A11 — Persian-only summary may under-serve developer + evaluator personas and compliance.**
Two of four personas are English-first, and disclaimer text is English. A Persian-only prose field risks
under-serving half the audience — and adding a field later is a **frozen-schema change**. **Proposal (was):**
bilingual `human_summary_fa` + `human_summary_en`. **✅ RESOLVED (ADR-014): rejected for MVP — Persian only
(`human_summary_fa`).** The reviewer confirmed the primary consumer is Persian-reading; EN is a future MINOR
additive field if a need is demonstrated. The disclaimer remains available in EN (envelope) and FA (per
compliance) independently of the summary language.

---

## 3. New decisions surfaced during Milestone 0

| # | Decision needed | **Final resolution (frozen)** |
|---|-----------------|--------------------------------------------|
| D1 | **Units for USD/IRR.** Source returns **Toman**. | ✅ **RESOLVED (ADR-014):** store & return in **IRT (Toman)**; `price.currency = "IRT"` for `USD_IRR`. **No Rial field, no `rial_multiplier`** in the contract — a consumer wanting Rial multiplies by 10 itself. Golden sample reconciled to IRT. |
| D2 | **USDT-as-USD proxy caveat.** `priceSellIRT` is USDT/IRT, not true USD/IRR. | ✅ **RESOLVED (ADR-014):** **do NOT surface the proxy** in the standard API/UI. Presented plainly as `USD/IRR` + number. Proxy fact recorded **internally only** (dictionary/ADR/decision log); no `proxy_note` payload field. **Reverses** the earlier "must be discoverable" stance (former compliance C-6 withdrawn). |
| D3 | **Event set for the trigger path.** §2 says "CPI/FOMC-class." | MVP event types: **US CPI, FOMC, US NFP** (manual entry). PCE/ECB reserved as config additions (zero code). |
| D4 | **External LLM provider abstraction (LOCKED by user directive).** The project **owns no model** — it calls a **configured External LLM Provider** via a provider abstraction. | See §3.1 below. Binding on the M1 architecture. |
| D5 | **API-only, no front-end (LOCKED by user directive, M1).** The system ships only a REST API + JSON contract; no UI is built. | [ADR-012](../adr/ADR-012-api-only-no-frontend.md). Milestone 0 UX rules become **consumer obligations**. |

### 3.1 — D4: External LLM Provider Abstraction (locked)

**User directive (2026-07-18):** This project does **not** own, train, fine-tune, or host any LLM. All LLM
interaction goes through a provider abstraction (an **LLM Gateway**) that talks to external providers
(OpenAI, Anthropic Claude, Google Gemini, DeepSeek, Grok, any future vendor). This is now a **locked
architectural constraint**, not an open item. It refines — does not replace — the master prompt's §5
`MarketReasoner` interface and ADR-007.

**Binding principles (verbatim intent, condensed):**

1. **Provider agnostic.** Nothing in the architecture assumes a specific vendor. Every LLM call flows through
   the abstraction:
   ```
   MarketReasoner (core-facing port)
     └── LLMGateway (selects provider, retries, fails over, records for replay)
           ├── OpenAIProvider
           ├── ClaudeProvider
           ├── GeminiProvider
           └── <FutureProvider>
   ```
   The core depends only on `MarketReasoner` and never knows which provider ran.
2. **No internal model.** All docs/code say "the configured External LLM Provider" / "the external language
   model" — never "our LLM/model/AI." Enforced by the Domain Dictionary ownership ban.
3. **Deterministic core unchanged.** Indicators, scores, MHI, Rule Engine, Rule Activation, event processing,
   decay, confidence, validation, guardrails, and evaluation stay 100% deterministic. The provider computes
   **no** market numbers.
4. **LLM jobs (exhaustive):** interpret unstructured news (Sentiment), detect novelty outside the rules,
   generate human summaries. Nothing else.
5. **All-providers-fail → Degraded Run.** Failover tries the next configured provider; if **all** fail, the
   pipeline continues and the Rule Engine still emits a valid Market State missing only the LLM-generated
   fields, flagged degraded + alert. Never a failed Run.
6. **Runtime configuration.** `provider`, `model`, `temperature`, `timeout`, retry/fallback order are
   config-driven (`config/models/providers.yaml`); changing provider requires **zero** code changes.
7. **Replay records provider identity.** Each Run records `provider`, `model`, prompt hash, and the provider
   response so historical runs remain reproducible (adds `versions.provider` alongside `versions.model`).
8. **Future providers = new adapter only.** Adding a vendor never touches business logic — only a new
   `Provider Adapter` behind the Gateway.

**Reconciliation with the master prompt (no conflict):** §5 already requires a provider-independent
`MarketReasoner` with adapters (Claude/GPT/local), capability flags, graceful degradation, and retry/timeout
(ADR-007). D4 makes the **multi-provider failover, runtime provider selection, and no-owned-model stance**
explicit and adds `versions.provider` to the replay record. `MarketReasoner` = the core-facing port;
`LLMGateway` = its multi-provider implementation. **ADR-007 is re-scoped** (see below) and remains the home
for this decision.

**ADR impact (now realized — architecture FROZEN 2026-07-18):**
- **[ADR-007](../adr/ADR-007-provider-agnostic-llm-gateway.md) — Provider-Agnostic LLM Gateway** — authored
  and **Accepted (frozen)**. Covers: MarketReasoner port, LLMGateway, Adapter pattern, config-driven
  providers, prompt independence, replay Call Record, automatic cost logging, provider metrics (operational
  only), health monitoring, circuit breaker, weighted/priority routing, offline test doubles.
- **[ADR-011](../adr/ADR-011-degraded-run-failure-isolation.md) — Degraded Run & Provider Failure Isolation**
  — authored and **Accepted (frozen)**. Split out of ADR-007: failover chain, deterministic-only Degraded Run,
  never-abort guarantee, honest absence of LLM fields, partial-success handling.
- **[Frozen architecture spec](../architecture/llm-provider-architecture.md)** — the binding reference
  (boundary diagram, component responsibilities, `providers.yaml` design, Call Record, routing, metrics,
  testing seams, future-provider matrix, and the 10 frozen invariants).
- **ADR-001** — reaffirmed: deterministic core is primary; the External LLM Provider is the exception layer.
- **ADR log** seeded at [../adr/README.md](../adr/README.md) (ADR-001…012; 007 & 011 Accepted, rest Proposed
  for M1).

> **FROZEN (2026-07-18):** The LLM-provider-independence architecture is frozen per user directive. Milestone 1
> designs the full system **on top of** this freeze and may not violate the invariants in the architecture
> spec §12. Changing a frozen invariant requires a **superseding ADR**.

**Everything else from Milestone 0 is unchanged** by D4: explainability, auditability, replayability,
deterministic scoring, versioning, Rule Engine, evaluation, compliance, market-observation positioning,
vision, personas, traceability, release policy, UX, KPI tree, and Domain Dictionary all stand. Only the LLM
ownership assumption changed.

---

## 4. Open questions carried forward (with working defaults)

These do **not** block the Milestone 0 product docs; each is documented with a default so work proceeds, and
each is flagged where it will block a later milestone.

| # | Open item | Working default (used in docs) | Blocks |
|---|-----------|-------------------------------|--------|
| ~~O1~~ | ~~**Summary language.**~~ | ✅ **RESOLVED (ADR-014): Persian only (`human_summary_fa`).** EN removed from MVP; future MINOR additive field if needed. | ~~Schema freeze (M2)~~ — closed |
| O2 | DXY and Tehran gold-coin (sekke) premium availability as inputs for USD/IRR domestic rules. | **Not guaranteed in MVP**; USD/IRR rules authored to *use them if present*, degrade to domestic news + trend if absent. | Rule Engine (M3). |
| O3 | Default LLM provider + real monthly USD budget. | **Claude** first adapter (matches environment); budget a **placeholder** you set before M4. | Cost governance (M6). |
| O4 | Disclaimer jurisdiction / regulatory framing. | **Generic "observation, not investment advice"**, no jurisdiction-specific text. | Compliance (this milestone, revisable). |
| O5 | Deployment operator/host. | **Self-hosted single node**, Docker. | Deployment (M5). |

> **Resolved & frozen (removed from Open Questions):** **O1** (FA-only), **D1** (IRT/Toman), **D2** (proxy
> internal-only) — see [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md). These no longer block
> Milestone 2.

---

## 5. Decision log (running)

| Date | Decision | Rationale | Supersedes |
|------|----------|-----------|------------|
| 2026-07-18 | USD/IRR sourced from internal kifpool USDT/IRT API | User directive (Q1); removes scraping/vendor risk | — |
| 2026-07-18 | News consumed from external pre-collected feed | User directive (Q3); keeps MVP scope tight | — |
| 2026-07-18 | Macro events entered manually | User directive (Q4); low volume, high reliability | — |
| 2026-07-18 | Staged enterprise ops (SQLite MVP → Postgres later) | A1; "no over-engineering" | pending ADR-006/010 |
| 2026-07-18 | **D4: External LLM Provider abstraction; no owned model; multi-provider failover** | User directive; provider-agnostic architecture | re-scopes ADR-007 |
| 2026-07-18 | **LLM-provider architecture FROZEN** — ADR-007 + ADR-011 Accepted; frozen spec published | User directive to freeze before M1 | binding on all future milestones |
| 2026-07-19 | **Milestone 1 architecture delivered** — full `docs/architecture/` set + ADR-001…013 Accepted | Milestone 1 deliverable | awaiting review |
| 2026-07-19 | **D5: API-only, no front-end** | User directive | ADR-012; UX rules → consumer obligations |
| 2026-07-19 | **O1/D1/D2 RESOLVED & FROZEN** — FA-only summary; USD/IRR in IRT; proxy internal-only | User directive; ADR-014 | unblocks Milestone 2 |

> **Status:** All contract-blocking open items are now resolved. **O1, D1, D2 frozen via
> [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md).** Remaining open items (O2–O5, OQ-3…OQ-10)
> do not block Milestone 2. Proceeding to **Milestone 2 — Contracts & Schemas**.
