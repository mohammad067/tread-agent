# Schema-to-Need Traceability Matrix

> **Milestone 0 deliverable.** Every field in the frozen `MarketStateRun` schema (master-prompt §11.1) mapped
> to the persona need and feature it serves. **Unmapped fields → flagged for removal. Unserved needs →
> flagged as gaps.** This matrix is a first-class contract check: at schema freeze (M2) every schema field
> must appear here with a non-empty "Serves."
> Personas P1–P4 per [02-personas.md](02-personas.md); features F-1…F-10 per [04-prd.md](04-prd.md); terms
> per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0 (derived from the §11.1 golden sample; reconciled to the actual schema in M2)

**Column key:** *Serves* = personas with a real need; *Feature* = PRD feature that produces it; *Need* = the
job it does; *Notes* = M0 decisions/challenges affecting it.

---

## Top-level / run identity

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `schema_version` | P2, P3 | F-8 | Contract versioning; safe integration & replay across versions | — |
| `run_id` (ULID) | P3, P2 | F-1, F-9 | Unique, sortable run identity for audit/replay/idempotency | Idempotent re-trigger no-op |
| `run_sequence` | P3, P1 | F-1 | Ordering runs; regime `previous_state` diffing | — |
| `trigger_type` | P3, P4 | F-1, F-10 | Separate scheduled vs. event evaluation buckets | Core to F-10 |
| `trigger_detail.event_id` | P4, P3 | F-1, F-5 | Which Macro Event drove an event Run | — |
| `trigger_detail.debounced_events` | P3 | F-1 | Debounce transparency (events aggregated) | Challenge basis: 30-min cooldown |
| `generated_at` | P1, P2, P3 | F-1 | Freshness display; SLA measurement | UTC |
| `is_degraded` | P1, P2, P3 | F-4, F-9 | Degraded-run transparency (LLM fields absent) | **Added M2**; ADR-011 |

## Versions block (audit/replay)

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `versions.rulebook` | P3, P4 | F-5, F-9 | Which Rule set produced this state (replay/audit) | — |
| `versions.mhi_weights` | P3 | F-3, F-9 | Which MHI weights (replay) | — |
| `versions.prompt_sentiment` (`v1#hash`) | P3 | F-4, F-9 | Exact prompt template + hash for replay | Hashed |
| `versions.prompt_synthesis` (`v1#hash`) | P3 | F-4, F-9 | Exact synthesis prompt for replay | Hashed |
| `versions.provider` | P3 | F-4, F-9 | Which External LLM Provider produced the LLM fields (replay/audit) | **New (D4)**; e.g. `openai`, `anthropic`, `gemini` |
| `versions.model` | P3 | F-4, F-9 | Provider model id; score-meaning drift control | e.g. `gpt-5.5`, `claude-sonnet-5` |
| `versions.pipeline` | P3 | F-9 | Pipeline code version for nightly replay diffing | — |
| `versions.pricing` | P3 | F-9 | Price-table version for reproducible cost | **Added M2**; ADR-007 D-6 |

## Regime block

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `regime.state` | P1, P4, P3 | F-7 | The market backdrop for every asset read | Enum of 4 |
| `regime.previous_state` | P1, P4 | F-7 | "What changed?" context | — |
| `regime.changed_this_run` | P1 | F-7 | Regime-change marker in UI Timeline | UX marker |
| `regime.confidence` | P1, P3 | F-7 | System confidence in the classification | **Deterministic** (challenge A2); labeled "system confidence" |
| `regime.drivers[].name` | P1, P4 | F-7 | Named driver of the regime | — |
| `regime.drivers[].weight_type` | P1, P3 | F-3, F-7 | `computed` vs `ordinal` honesty | UX distinct rendering (X-3) |
| `regime.drivers[].weight` | P1, P3 | F-3 | Real % for computed drivers | Only when `computed` |
| `regime.drivers[].level` | P1 | F-4 | Ordinal level for provider-estimated drivers | dominant/major/moderate/minor |
| `regime.drivers[].detail` | P1, P4 | F-7 | Human-readable driver explanation (grounded numbers) | — |

## Asset block (per asset, ×6)

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `symbol` | all | F-2 | Asset identity | BTC/ETH/GOLD/WTI/USD_IRR/TOTAL_MCAP |
| `asset_class` | P2, P3 | F-2 | Drives full-vs-index indicator shape | **Added M2**; A8 (index assets) |
| `price.value` | P1, P4 | F-2 | Current price | USD_IRR in IRT (D1) |
| `price.currency` | P1, P2 | F-2 | Unit of the price | `IRT` (Toman) for USD_IRR; **ADR-014** |
| `price.as_of` | P1, P3 | F-2 | Price timestamp for freshness | — |
| `price.is_stale` | P1, P4 | F-2 | Dim stale prices; honesty | UX dim (X-4) |
| `price.stale_reason` | P1 | F-2 | Why stale (e.g., tehran_market_closed_weekend) | — |
| `price.venue_aggregation` | P4, P3 | F-2 | How multi-venue price was aggregated (median_N) | ADR-009 |
| `changes.{6h,24h,7d,30d}` | P1, P4 | F-2 | Multi-horizon momentum | — |
| `indicators.rsi_14` | P1, P4 | F-2, F-3 | Momentum/overbought-oversold context | — |
| `indicators.macd_state` | P1, P4 | F-2, F-3 | Trend transition state | Enum |
| `indicators.ema_20_50` | P1, P4 | F-2, F-3 | Trend structure | Enum |
| `indicators.atr_pct` | P4, P3 | F-2, F-3, F-9 | Volatility context; Noise-Threshold base | Feeds ATR-relative bands (A5) |
| `indicators.volume_ratio_20d` | P1, P4 | F-2, F-3 | Participation/conviction | — |
| `scores.trend` | P1, P4, P3 | F-3 | Deterministic trend read | [-1,1] |
| `scores.risk` | P1, P4, P3 | F-3 | Deterministic risk read | [0,1] |
| `scores.sentiment` | P1, P4, P3 | F-4 | News sentiment from the External LLM Provider | [-1,1]; only provider-set score |
| `scores.confidence` | P1, P3 | F-3, F-4 | System confidence in the asset read | Deterministic; "system confidence" |
| `market_health_index` | P1, P4 | F-3 | 0–100 at-a-glance condition | Weighted projection (config) |
| `regime_sensitivity` | P4, P3 | F-7 | Whether regime governs this asset | `low` for USD_IRR |
| `activated_rules[].rule_id` | P1, P4, P3 | F-5 | Which Rule fired | — |
| `activated_rules[].strength` | P1, P4 | F-5 | Effect magnitude | ordinal |
| `activated_rules[].horizon` | P4 | F-5 | Effect time horizon | — |
| `activated_rules[].decay_remaining` | P4, P3 | F-5, F-6 | How much of the effect remains (decay) | [0,1] |
| `causal_links[].from/to/direction` | P1, P4 | F-5 | The causal chain for the drill-down | Presentation artifact |
| `causal_links[].via_rule` | P1, P3 | F-5 | Attribution to the exact Rule | Cross-checks activated_rules |
| `human_summary_fa` | P1, P4 | F-4 | Plain-language Persian read | Style guide (X-6); **FA-only, ADR-014** |
| `novelty_flags[]` | P3, P4 | F-4 | Dynamics outside the rule set → rule backlog | — |
| `data_gaps[]` | P1, P3 | F-2 | Declared missing/excluded inputs | Degrade-not-fail |

## Global block

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `global.fear_greed.value/label` | P1, P4 | F-2 | Crypto sentiment context | **Crypto-only input** (A6) |
| `global.btc_dominance` | P4, P3 | F-2 | Crypto rotation context | Fixed stablecoin method (A9/ADR-009) |
| `global.total_market_cap_usd` | P1, P4 | F-2 | Crypto market size context | Index series (A8) |
| `global.expectation_context.recent_surprises[]` | P4, P3 | F-2 | Reserved slot fed by event surprises | Phase 4 grows it |
| `global.onchain_context` | P3 | F-2 | Reserved slot (Blockchain persona) | `null` in MVP |

## Envelope / compliance

| Field | Serves | Feature | Need | Notes |
|-------|--------|---------|------|-------|
| `guardrail_flags[]` | P3, P1 | F-8 (guardrails) | Surface deterministic-validation flags | UX severity |
| `disclaimer` | all, compliance | X-5 | Observation-not-advice framing in the payload | Required |
| `meta.api_version` (envelope) | P2 | F-8 | API contract version | Response envelope |
| `meta.next_scheduled_run` (envelope) | P1, P2 | F-1 | When the next state arrives | — |
| `meta.disclaimer` (envelope) | compliance | X-5 | Disclaimer at API layer | — |

---

## Unmapped fields (flag for removal)

None at Milestone 0. Every field in the §11.1 golden sample maps to at least one persona need. **Watch item:**
if TOTAL_MCAP/BTC-Dominance keep the full indicator suite despite challenge A8, those extra indicator fields
for index assets would become *unserved* and should be removed — tracked as a schema-shape decision for M2.

## Unserved needs (flag as gaps)

| Need | Persona | Current schema support | Resolution |
|------|---------|------------------------|------------|
| ~~English human summary~~ | P2, P3, P4 | `human_summary_fa` only | ✅ **Closed (ADR-014): FA-only for MVP.** Not a gap — EN deliberately out of scope; future MINOR additive field if needed. |
| ~~USDT-proxy transparency for USD/IRR~~ | P2, P4 | Presented plainly as `USD_IRR` (IRT) | ✅ **Closed (ADR-014): proxy is internal-only, not surfaced.** Not a gap — deliberate presentation choice; no `proxy_note` field. |
| Per-asset staleness threshold visibility | P1 | Config-side only | Acceptable: config, not payload. Not a schema gap. |
| Cost/token per run (governance) | P3, ops | Not in `MarketStateRun` (correctly — it's run metadata) | Lives in Event Log/metrics, not the public contract. Not a gap. |

## Matrix invariants (enforced at schema freeze, M2)

1. Every schema field appears in this matrix with a non-empty **Serves**.
2. Every **●●● persona output** in [02-personas.md](02-personas.md) has ≥ 1 backing field here.
3. Any field added/removed in a schema change updates this matrix in the **same** milestone (§8: divergence is
   a defect).
