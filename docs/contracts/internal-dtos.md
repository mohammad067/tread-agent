# Internal DTO Contracts

> **Milestone 2 — Contracts & Schemas.** Field-by-field specs for every **internal** DTO that crosses a module
> boundary. These become `schemas/internal/*.v1.json` (generated after approval). **Design document — no code.**
> Each DTO is versioned (`v1`). Terms binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md); component owners per
> [../architecture/module-catalog.md](../architecture/module-catalog.md).
> **Version:** 1.0.0

## DTO map (who produces/consumes what)

```mermaid
graph LR
  ING[Ingestion] -->|RawSnapshot| FE[FeatureEngine]
  FE -->|FeatureSet| RE[RuleEngine]
  FE -->|FeatureSet| SC[ScoringEngine]
  RE -->|RuleActivation[]| SC
  NW[NewsWeigher] -->|NewsDigest| MR1[MarketReasoner.analyze_sentiment]
  MR1 -->|ReasoningResponse:sentiment| SC
  SC -->|StateVector| MR2[MarketReasoner.synthesize]
  RE -->|RuleActivation[]| MR2
  MR2 -->|ReasoningResponse:synthesis| GR[Guardrails]
  MR1 & MR2 -.->|CallRecord| EL[Event Log]
```

---

## 1. `RawSnapshot` (v1) — Ingestion → Event Log & FeatureEngine

Immutable capture of one source's output for one run.

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `source_id` | string | M | e.g., `kifpool`, `crypto_median`, `fear_greed`, `news_feed`, `event_manual`. |
| `symbol` | string \| null | M,N | Asset symbol, or null for global sources. |
| `payload` | object (raw) | M | Verbatim source data. |
| `as_of` | string ISO-8601 | M | Source timestamp. |
| `is_stale` | boolean | M | Staleness at capture. |
| `stale_reason` | string (open vocab) | C | Present iff stale. |
| `deviation_flags` | array\<object\> | M (may be empty) | Cross-source divergence records (ADR-009). |
| `content_hash` | string | M | Hash of `payload` for replay integrity. |

## 2. `FeatureSet` (v1) — FeatureEngine → Rule/Scoring (PURE, replay-critical)

All deterministic math outputs for one run. Byte-reproducible from `RawSnapshot`s + config versions.

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `run_id` | string | M | Correlation. |
| `per_asset` | map\<symbol, AssetFeatures\> | M | See §2.1. |
| `global_features` | object | M | F&G (crypto-context), dominance, total mcap, cross-asset aggregates. |
| `event_features` | array\<EventFeature\> | M (may be empty) | Surprises + proximity (§2.2). |
| `news_features` | object | M | Effective weights (feeds NewsDigest). |
| `config_versions` | object | M | The config/weights/decay versions used (pin for replay). |

### 2.1 `AssetFeatures`
`indicators` (per §5.2 of the schema spec, class-dependent), `changes` (6h/24h/7d/30d), `atr_pct`,
`volume_ratio_20d`, `event_proximity` (hours to nearest relevant event), `decay_inputs` (for rule
`decay_remaining`). All numbers; missing → recorded in `data_gaps`.

### 2.2 `EventFeature`
| Field | Type | Notes |
|-------|------|-------|
| `event_id` | string | References `macro_events`. |
| `event_type` | string | `us_cpi`\|`fomc`\|`us_nfp`. |
| `surprise` | number | `actual − consensus` (event-natural units). |
| `surprise_sigma` | number \| null | Standardized surprise if a historical stdev is available. |
| `proximity_hours` | number | Time since/until the event. |

## 3. `NewsDigest` (v1) — NewsWeigher → LLM Call #1

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `run_id` | string | M | — |
| `items` | array\<WeightedNewsItem\> | M (may be empty) | Ranked by `effective_weight`. |
| `weighting_versions` | object | M | source-quality + half-life versions (pin for replay). |

**`WeightedNewsItem`:** `news_id`, `title`, `source`, `published_at`, `source_quality` (0–1), `relevance`
(0–1), `recency_decay` (0–1), `effective_weight` (0–1, = product). **The LLM consumes these; never assigns
them** (F-6).

## 4. `ReasoningRequest` (v1) — pipeline → MarketReasoner (both calls)

The neutral input to the provider-agnostic port. **Contains only numbers already computed** (grounding).

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `run_id` | string | M | — |
| `job` | enum closed | M | `sentiment` \| `synthesis`. |
| `payload` | object | M | For `sentiment`: the `NewsDigest` + asset list. For `synthesis`: the `StateVector` + `RuleActivation[]` + sentiment result. |
| `constraints` | object | M | `language: "fa"` (ADR-014), `grounding: true`, `output_schema_ref` (which `ReasoningResponse` variant), `max_tokens`, `temperature`. |
| `self_consistency` | object | O | `{enabled:bool, samples:int}` — off by default (A3). |

> The request is **provider-neutral**; the PromptBuilder renders it to a `RenderedPrompt` (identical across
> vendors). No vendor fields here.

## 5. `ReasoningResponse` (v1) — MarketReasoner → pipeline

Two variants, both structured-output-validated. On provider failure the pipeline receives a **degraded
marker** instead (never a fabricated response).

### 5.1 Sentiment variant
| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `per_asset_sentiment` | map\<symbol, number [-1,1]\> | M | Only score the LLM sets. |
| `global_sentiment` | number [-1,1] | M | — |
| `confidence_signals` | object | O | Optional model-reported signals; **do not** override deterministic confidence. |

### 5.2 Synthesis variant
| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `per_asset` | map\<symbol, object\> | M | Each: `human_summary_fa` (string, Persian), `ordinal_drivers` (array\<Driver ordinal\>), `novelty_flags` (array\<string\>), `data_gap_notes` (array\<string\>). |
| `grounding_ok` | boolean | O | Model self-report; the **deterministic guardrail** is authoritative. |

> **No numbers may appear that aren't in the request** (grounding); the Guardrails stage enforces this
> deterministically regardless of `grounding_ok`.

## 6. `StateVector` (v1) — ScoringEngine → LLM Call #2 & Guardrails

The deterministic core's finished numeric output for one run: per-asset `scores` (trend/risk/confidence),
`market_health_index`, `regime` (state/previous/changed/confidence/computed-drivers), plus the
`RuleActivation[]` and `CausalLink[]`. This is what synthesis narrates and what the final `MarketStateRun`
is assembled from.

## 7. `RuleActivation` (v1) & `CausalLink` (v1)

Identical shape to the public-schema §5.4/§5.5 objects (they are surfaced directly). Internally each
`RuleActivation` also carries `matched_condition` (the evaluated expression) and `source_rule_version` for
replay/audit; these internal-only fields are **not** surfaced in the public `MarketStateRun`.

## 8. `CallRecord` (v1) — LLMGateway → Event Log

The per-attempt replay/cost/metrics unit. Full field list in
[../architecture/database.md §4.5](../architecture/database.md) and
[../architecture/llm-provider-architecture.md §5](../architecture/llm-provider-architecture.md). Restated as a
DTO contract: `run_id`, `llm_job`, `attempt_index`, `provider`, `model_id`, `prompt_version`, `prompt_hash`,
`rendered_prompt`, `response`, `response_hash`, `latency_ms`, `input_tokens`, `output_tokens`,
`estimated_cost`, `retries`, `finish_reason`, `outcome`, `created_at`.

## 9. `DegradedMarker` (v1) — MarketReasoner → pipeline (ADR-011)

Returned instead of a `ReasoningResponse` when all providers fail for a job.

| Field | Type | Notes |
|-------|------|-------|
| `job` | enum closed | `sentiment`\|`synthesis`. |
| `reason` | string (open vocab) | e.g., `all_providers_exhausted`, `structured_output_invalid`. |
| `last_attempt` | object | `{provider, model_id}` of the final attempt (for `versions.*`). |

## 10. Contract invariants (contract tests, M3+)

1. Every DTO validates against its `schemas/internal/*.v1.json`.
2. `ReasoningRequest.payload` numbers ⊇ any number appearing in `ReasoningResponse` (grounding) — property
   test.
3. `effective_weight == source_quality × relevance × recency_decay` (± float epsilon) — unit test.
4. A `DegradedMarker` never coexists with fabricated LLM fields in the assembled run.
5. Every `CallRecord` is written for every attempt, including failures.
