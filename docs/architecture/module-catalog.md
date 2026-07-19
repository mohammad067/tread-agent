# Module / Service Catalog

> **Milestone 1.** Every module with its **single responsibility**, **inputs**, **outputs**, and **owner
> boundaries**. This is the authoritative map of *what each component may and may not do*. Terms binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md). Dependency rules per
> [overview.md §2](overview.md). **No code.**
> **Version:** 1.0.0

## Legend
- **Layer:** Data (deterministic core + persistence) · Reasoning (provider-agnostic LLM) · Presentation.
- **Purity:** *Pure* = no I/O, deterministic, replay-safe. *I/O* = touches network/disk/clock.
- **May not** = hard boundary; a violation is a defect caught by the import-boundary lint (from M3).

---

## A. Domain Core (Data layer — PURE, no I/O, no LLM, no framework)

Maps to `src/market_state_engine/{core,features,rules,news,scoring,guardrails}/`.

### A1. `core` — Domain models & ubiquitous-language types
- **Responsibility:** Define the domain vocabulary as types: `Asset`, `Regime`, `Score`, `Driver`,
  `RuleActivation`, `CausalLink`, `NewsItem`, `MacroEvent`, `Surprise`, `RunContext`, and the DTOs
  (`ReasoningRequest`, `ReasoningResponse`, `NewsDigest`). One home for the Domain Dictionary terms.
- **Inputs:** none (definitions only). **Outputs:** types imported by every other module.
- **Purity:** Pure. **May not:** import any other layer, any framework, any vendor SDK, or perform I/O.
- **Owner:** Backend + AI Architect (DTOs). **Why isolated:** a single source of truth for terms guarantees
  the "binding ubiquitous language" rule and lets every layer share types without cycles.

### A2. `features` — FeatureEngine (all deterministic math)
- **Responsibility:** Compute indicators (`rsi_14`, `macd_state`, `ema_20_50`, `atr_pct`,
  `volume_ratio_20d`), multi-horizon changes (6h/24h/7d/30d), **event proximity**, **surprise** values,
  **news recency-decay** weights, and rule **decay_remaining**. All arithmetic lives here.
- **Inputs:** raw ingested snapshots (prices, volumes, events), config (asset config, half-lives).
- **Outputs:** a computed `FeatureSet` per asset + global.
- **Purity:** Pure (deterministic function of inputs + config versions). **May not:** call the network, read
  the clock directly (time is injected via `RunContext`), or touch the LLM.
- **Owner:** Backend; Trader reviews indicator semantics (A5 ATR-relative logic).
- **Why:** "the LLM is never responsible for arithmetic" (§7) is structurally guaranteed by centralizing math
  here and forbidding I/O — which is also what makes replay byte-identical.

### A3. `rules` — RuleEngine (loader, matcher, conflict resolution)
- **Responsibility:** Load the versioned YAML rulebook; **match** rules against current events/conditions using
  **surprise-based** conditions; resolve **conflicts** (same asset, opposing effects) deterministically;
  emit `RuleActivation`s + causal edges. Only **activated** rules are returned (for prompt injection).
- **Inputs:** `FeatureSet` (surprises, conditions), the loaded rulebook (+ version), regime (for regime-guarded
  rules — challenge A4).
- **Outputs:** `list[RuleActivation]` with strength/horizon/decay + `list[CausalLink]`.
- **Purity:** Pure. **May not:** invent effects not in a rule; call the LLM; author rationale (rationale is
  authored by humans in YAML with Trader sign-off — ADR-008).
- **Owner:** Backend (engine) + **Senior Trader** (rule content & `economic_rationale`, hard gate ADR-008).
- **Why deterministic & YAML:** auditability and replay (ADR-001, ADR-003); the causal graph is a presentation
  artifact assembled *only* from these edges (§3), never LLM-invented.

### A4. `news` — NewsWeigher
- **Responsibility:** Compute `effective_weight = source_quality × relevance × recency_decay` per News Item;
  rank and assemble the **News Digest**. The LLM consumes these weights; it never assigns them (F-6).
- **Inputs:** `list[NewsItem]` (from the external feed), source-quality config, decay half-lives, run time.
- **Outputs:** `NewsDigest` (weighted, ranked).
- **Purity:** Pure. **May not:** call the LLM; fetch news (the feed is ingested upstream — Q3).
- **Owner:** Backend; AI Architect (digest shape). **Why:** honest, replayable weighting isolates the "nice
  narrative" bias risk that ADR-002 addresses.

### A5. `scoring` — ScoringEngine + RegimeClassifier
- **Responsibility:** Compute **trend_score** (`[-1,1]`), **risk_score** (`[0,1]`), **market_health_index**
  (0–100 weighted projection from `config/weights/`), and classify **Regime** (mostly deterministic) with a
  **deterministic `confidence`** (concordance + distance-to-boundary — challenge A2). Regime is computed
  **first**; USD/IRR is analyzed on domestic drivers (`regime_sensitivity: low` — ADR-005).
- **Inputs:** `FeatureSet`, `RuleActivation`s, sentiment (if present), MHI weight config (+ version).
- **Outputs:** per-asset `Scores`, `market_health_index`, global `Regime` (+ previous_state, changed_this_run,
  confidence, drivers).
- **Purity:** Pure. **May not:** let the LLM set any number; read weights from code (weights are config).
- **Owner:** Backend + Trader (regime taxonomy, thresholds). **Why:** all market numbers are code-computed,
  versioned, and replayable (§7, ADR-001).

### A6. `guardrails` — Guardrails (deterministic post-validation)
- **Responsibility:** After synthesis, run deterministic checks: schema validation, range checks, consistency
  (e.g., all-bullish indicators with strongly negative trend → flag), **contradiction** between summary and
  scores, **grounding** (summary references only numbers present in the request), and **degraded-run** honesty
  (LLM fields absent, not fabricated — ADR-011). Emits `guardrail_flags[]`; policy is **publish-with-flags**
  (or block per taxonomy — see [cross-cutting.md](cross-cutting.md)).
- **Inputs:** the assembled `MarketStateRun` candidate + the `ReasoningRequest`/response.
- **Outputs:** `guardrail_flags[]` + a publish/block decision.
- **Purity:** Pure (property-tested with hypothesis). **May not:** modify scores (only flag); call the LLM.
- **Owner:** Backend + AI Architect. **Why:** the last deterministic line of defense; property tests give
  broad coverage of the flagging logic.

---

## B. Reasoning layer (provider-agnostic — governed by frozen ADR-007/011)

Maps to `src/market_state_engine/reasoning/`. Full frozen spec:
[llm-provider-architecture.md](llm-provider-architecture.md).

### B1. `MarketReasoner` (PORT) — the only LLM-facing type the Core sees
- **Responsibility:** Define `analyze_sentiment(ReasoningRequest) → ReasoningResponse` and
  `synthesize(ReasoningRequest) → ReasoningResponse`. The **sole** interface the pipeline depends on.
- **Inputs/Outputs:** neutral DTOs only. **Purity:** interface (no impl). **May not:** name any vendor.
- **Owner:** AI Architect. **Why:** the frozen boundary (invariant #1).

### B2. `LLMGateway` — implements `MarketReasoner`
- **Responsibility:** Orchestrate a call: build the request → PromptBuilder → route (priority/weighted) →
  retry/timeout → **failover** across providers → health/circuit checks → record a **Call Record** →
  return a `ReasoningResponse` or a **degraded marker**. Owns orchestration, **not** business logic.
- **Inputs:** `ReasoningRequest`, provider config (Registry), prompt templates.
- **Outputs:** `ReasoningResponse` (or degraded), Call Records to the Event Log.
- **Purity:** I/O (network). **May not:** compute any market number; author prompts; know vendor specifics
  beyond the adapter interface.
- **Owner:** Backend + AI Architect.

### B3. `ProviderRegistry`, `Router`, `RetryPolicy`, `TimeoutPolicy`, `ProviderHealthMonitor`, `CircuitBreaker`
- **Responsibility:** Registry loads enabled providers + policies from `providers.yaml`; Router picks order
  (priority/weighted) among healthy providers; Retry/Timeout enforce per-provider policy; HealthMonitor tracks
  rolling stats; CircuitBreaker trips/recovers failing providers. All **config-driven**.
- **Inputs:** `providers.yaml`, live call outcomes. **Outputs:** routing decisions, health/breaker state.
- **Purity:** I/O/stateful (health, breaker). **May not:** influence market outputs — **operational only**
  (ADR-007 D-7).
- **Owner:** Backend.

### B4. `PromptBuilder` → `RenderedPrompt`
- **Responsibility:** Render versioned application templates (`prompts/`) + `ReasoningRequest` into a
  **provider-neutral** `RenderedPrompt`; compute `prompt_hash` on the neutral text (identical across vendors).
- **Inputs:** `ReasoningRequest`, template (+ version). **Outputs:** `RenderedPrompt` + `prompt_hash`.
- **Purity:** Pure. **May not:** contain vendor formatting; live inside an adapter.
- **Owner:** AI Architect. **Why:** prompt independence (frozen invariant #4).

### B5. `ProviderAdapter` interface + concrete adapters (`OpenAIProvider`, `ClaudeProvider`, `GeminiProvider`, …)
- **Responsibility:** Translate `RenderedPrompt` + `CallParams` to/from one vendor's API; map structured-output
  mechanism, token accounting, and error semantics to neutral types.
- **Inputs:** `RenderedPrompt`, `CallParams`. **Outputs:** `RawProviderResult` (text, tokens, finish_reason).
- **Purity:** I/O. **May not:** contain business logic or alter prompt semantics.
- **Owner:** Backend. **Why:** add-a-provider = one adapter + one config entry (frozen invariant #3).

### B6. Test-double adapters: `FakeProvider`, `MockProvider`, `DeterministicProvider`, `ReplayProvider`
- **Responsibility:** Offline, internet-free provider implementations for dev/unit/replay tests.
  `ReplayProvider` serves recorded Call Records; `DeterministicProvider` is a fixed function of input.
- **Owner:** Backend/QA. **Why:** hermetic CI (frozen invariant #10).

---

## C. Ingestion (Data layer — I/O behind interfaces)

Maps to `src/market_state_engine/ingestion/` (`base.py` + one module per source + `mocks/`).

### C1. Source ports & adapters
- **Responsibility:** Define source interfaces and one adapter per source, each returning an **immutable raw
  snapshot** tagged with `as_of`, `is_stale`, and deviation flags. Ports:
  - `PriceSource` — per asset. **USD/IRR = kifpool** adapter (`priceSellIRT`; internally a USDT/IRT proxy;
    returned in **IRT/Toman** with `currency:"IRT"`; proxy nature **not surfaced** — ADR-014; 30–60s cache,
    stale-fallback — Q1/ADR-014). Crypto prices use **median-across-venues** with deviation flags (ADR-009).
  - `IndicatorInputSource` — OHLCV series feeding the FeatureEngine.
  - `FearGreedSource` — **crypto-only** input (challenge A6).
  - `DominanceSource` / `TotalMcapSource` — index/context series (challenge A8), fixed stablecoin methodology
    (ADR-009).
  - `NewsSource` — reads the **external pre-collected** feed into `NewsItem`s (Q3).
  - `EventSource` — reads **manually entered** Macro Events (consensus/actual) (Q4).
- **Inputs:** external APIs/feeds/files. **Outputs:** immutable raw snapshots → Event Log.
- **Purity:** I/O. **May not:** compute features (that's A2); silently average divergent sources (§7, ADR-009);
  fail the run on a single stale/missing source (mark `is_stale`/`data_gaps` instead — §4.2).
- **Owner:** Backend; **Blockchain persona** owns crypto integrity (ADR-009); Trader owns market-hours/staleness.
- **`mocks/`:** deterministic mock ingestors for dev/CI (no internet).

---

## D. Persistence (Data layer)

Maps to `src/market_state_engine/persistence/`. Schema: [database.md](database.md).

### D1. Repositories
- **Responsibility:** Read/write `runs`, `run_inputs`, `run_outputs`, `outcomes`, `call_records`,
  `rules_versions`, `config_versions`, `news_items`, `macro_events`, `evaluation_reports` behind interfaces.
- **Purity:** I/O. **May not:** contain business logic. **Owner:** Backend.

### D2. Event Log (append-only)
- **Responsibility:** Persist **immutable input snapshots**, generated prompts (+ hashes), all **versions**,
  full output, and **Call Records**. Append-only; included in backups (losing it destroys replay — §12).
- **Purity:** I/O (append-only). **May not:** be mutated or deleted. **Owner:** Backend.
- **Why:** the scientific backbone (ADR-004); everything replay/eval reads from here.

---

## E. Pipeline / Orchestration

Maps to `src/market_state_engine/pipeline/`.

### E1. Pipeline Orchestrator + `RunContext`
- **Responsibility:** Sequence the lifecycle (§4): trigger → ingest → features → rule match → LLM #1 → scoring
  → regime → LLM #2 → guardrails → persist/publish → (async) outcome. Owns **idempotency** (re-triggering a
  `run_id` is a no-op), **time injection** (deterministic clock via `RunContext`), stage error policy, and
  **degraded-run** assembly (ADR-011).
- **Inputs:** trigger (scheduled/event), all module outputs. **Outputs:** a persisted `MarketStateRun`.
- **Purity:** Orchestration (I/O at edges; pure core calls in between). **May not:** contain math or vendor
  knowledge; call a vendor directly (only via `MarketReasoner`).
- **Owner:** Backend + Architect. **Why:** one place owns sequencing so every other module stays single-purpose
  and replay-reproducible.

### E2. Scheduler + Event Trigger
- **Responsibility:** Fire scheduled runs (6h cron) and event runs (with **debounce/cooldown**: ≤1 event run
  / 30 min; events aggregate). Assign `run_id`/`run_sequence`/`trigger_type`. Missed-run detection (§12).
- **Purity:** I/O (clock/timer). **May not:** run pipeline logic itself (delegates to E1).
- **Owner:** Backend.

---

## F. Evaluation

Maps to `src/market_state_engine/evaluation/`. Detail: [pipelines.md](pipelines.md).

### F1. OutcomeRecorder
- **Responsibility:** Async job attaching realized **Outcomes** at +6h/+24h (returns vs **ATR-relative Noise
  Threshold** — A5, realized volatility) to run records.
- **Purity:** I/O (reads later market data). **Owner:** Backend + Trader (noise bands).

### F2. ReplayHarness + Ablation runner
- **Responsibility:** Re-run any pipeline **variant** offline over immutable snapshots using `ReplayProvider`;
  run ablations **A** (rules-only) → **B** (+deterministic-news) → **C** (+LLM-sentiment) → **D** (full) for
  paired comparison. Deterministic core replays byte-identically.
- **Purity:** Orchestration over stored inputs (no live network). **Owner:** Backend + Evaluator (P3).

### F3. Metrics + Report generator
- **Responsibility:** Directional accuracy vs **persistence** & **always-neutral** baselines, **Brier**,
  **calibration buckets**, separated by `trigger_type`; monthly report (§11.6); pre-registered decision-rule
  status.
- **Purity:** Pure over stored data. **May not:** let provider metrics leak into model-quality metrics (§7).
- **Owner:** Evaluator (P3) + Backend.

---

## G. Presentation

### G1. API (FastAPI)
- **Responsibility:** Serve the JSON contract: latest state, run by id, run range, evaluation summary, health.
  Static API key auth; rate limiting; disclaimer in `meta`. Detail: [api-design.md](api-design.md).
- **Purity:** I/O. **May not:** compute or reshape market numbers beyond envelope wrapping.
- **Owner:** Backend.

### G2. Observability exporter
- **Responsibility:** Export structured logs (`run_id` correlated) and metrics (run latency by stage, LLM
  latency/tokens/cost, guardrail-flag rate, data-gap rate, LLM-vs-rules divergence). Detail:
  [cross-cutting.md](cross-cutting.md).
- **Purity:** I/O. **Owner:** Backend.

---

## Dependency rules (summary — enforced by import-boundary lint from M3)

| From ↓ / May import → | core | features/rules/news/scoring/guardrails | ingestion | persistence(ports) | MarketReasoner | LLMGateway/adapters | pipeline | api |
|---|---|---|---|---|---|---|---|---|
| **core** | ✔ | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ |
| **features/rules/news/scoring/guardrails** | ✔ | ✔(siblings via core types) | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ |
| **ingestion** | ✔ | ✖ | ✔ | ports only | ✖ | ✖ | ✖ | ✖ |
| **persistence** | ✔ | ✖ | ✖ | ✔ | ✖ | ✖ | ✖ | ✖ |
| **reasoning (gateway/adapters)** | ✔ | ✖ | ✖ | ports (Call Record) | ✔ | ✔ | ✖ | ✖ |
| **pipeline** | ✔ | ✔ | ✔ | ✔ | ✔ | ✖ (only via port) | ✔ | ✖ |
| **api** | ✔ | ✖ | ✖ | ✔ | ✖ | ✖ | ✔ | ✔ |

Legend: ✔ allowed · ✖ forbidden (defect if violated). The two load-bearing rules: **no core module imports I/O
or a vendor SDK**, and **the pipeline reaches the LLM only through `MarketReasoner`**.
