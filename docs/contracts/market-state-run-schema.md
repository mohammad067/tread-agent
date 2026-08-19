# MarketStateRun v1.0.0 — Schema Specification

> **Milestone 2 — Contracts & Schemas.** The **field-by-field** specification of the frozen public contract
> `market_state_run.v1.0.0.json`. This is the **design document**; the JSON Schema file is generated from it
> after approval. Every field traces to [../product/05-traceability-matrix.md](../product/05-traceability-matrix.md).
> Reflects the resolved decisions: **FA-only summary, USD/IRR in IRT, proxy internal-only** (ADR-014),
> **index-class assets** (A8), **deterministic regime confidence** (A2), **reserved slots** (ADR-013).
> Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> **Version:** 1.0.0 (contract freeze candidate)

## 0. Conventions

- **Req?** — `M` mandatory (schema `required`), `O` optional, `N` nullable (may be `null`), `C` conditional
  (present only for some asset classes / run types — condition stated).
- Types: JSON types + noted ranges/enums. **Closed enum** = fixed `enum`; **open vocab** = validated against a
  controlled vocabulary (§ versioning-strategy §3), extensible without MAJOR.
- All timestamps are **ISO-8601**; UTC unless an explicit offset is shown (USD/IRR uses `+03:30`).
- "Deterministic" fields are produced by the core; "LLM" fields by the External LLM Provider (absent on a
  Degraded Run — ADR-011).

---

## 1. Root object

| Field | Type | Req? | Source | Notes |
|-------|------|------|--------|-------|
| `schema_version` | string (SemVer) | M | system | `"1.0.0"` — frozen contract. |
| `run_id` | string (ULID) | M | system | Unique, sortable; idempotency + correlation key. |
| `run_sequence` | integer ≥ 0 | M | system | Monotonic run ordering. |
| `trigger_type` | enum **closed** | M | system | `scheduled` \| `event`. Evaluation bucket key. |
| `trigger_detail` | object | M | system | See §2. |
| `generated_at` | string (ISO-8601 UTC) | M | system | Run production time (freshness/SLA). |
| `is_degraded` | boolean | M | system | `true` when LLM fields are absent (ADR-011). **New vs. §11.1 sample** — see §11 reconciliation. |
| `versions` | object | M | system | See §3. |
| `regime` | object | M | deterministic | See §4. |
| `assets` | array\<Asset\> | M | mixed | Exactly the 6 MVP assets; see §5. |
| `global` | object | M | mixed | See §6. |
| `guardrail_flags` | array\<Flag\> | M (may be empty) | deterministic | See §7. |
| `disclaimer` | string | M | system | Canonical compliance text (English), see [../product/07-compliance.md](../product/07-compliance.md). |

## 2. `trigger_detail`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `event_id` | string | C | Present when `trigger_type=event`; references `macro_events.event_id`. |
| `debounced_events` | integer ≥ 0 | C | Count of events aggregated into this run (event runs). |
| `scheduled_for` | string (ISO-8601) | O | The cron slot this run fills (scheduled runs). |

## 3. `versions` (reproducibility block — every field mandatory)

| Field | Type | Notes |
|-------|------|-------|
| `rulebook` | string SemVer | e.g., `"1.4.0"`. |
| `mhi_weights` | string SemVer | e.g., `"1.1.0"`. |
| `prompt_sentiment` | string `vN#hash` | e.g., `"v1#a3f9c2"`. |
| `prompt_synthesis` | string `vN#hash` | e.g., `"v1#7be014"`. |
| `provider` | string | Vendor id, e.g., `"openai"` (**added by D4/ADR-007**). On degraded run: last attempted. |
| `model` | string | Model id, e.g., `"gpt-5.5"`. On degraded run: last attempted. |
| `pipeline` | string SemVer | e.g., `"0.9.2"`. |
| `pricing` | string SemVer | Price-table version used for cost (ADR-007 D-6). |

## 4. `regime` (deterministic; computed first — ADR-005)

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `state` | enum **closed** | M | `risk_on` \| `risk_off` \| `transition` \| `event_driven`. |
| `previous_state` | enum closed \| null | M,N | Prior run's regime; `null` for the first-ever run. |
| `changed_this_run` | boolean | M | UI regime-change marker. |
| `confidence` | number [0,1] | M | **Deterministic** (concordance + distance-to-boundary — A2). "System confidence," never probability. |
| `drivers` | array\<Driver\> | M (may be empty) | See §4.1. |

### 4.1 `Driver` (used by regime and, per §5, informing assets)

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `name` | string (open vocab) | M | Driver id, e.g., `cpi_surprise`. |
| `weight_type` | enum **closed** | M | `computed` \| `ordinal`. |
| `weight` | number [0,1] | C | **Present iff** `weight_type=computed` — a real fraction from the scoring formula. |
| `level` | enum **closed** | C | **Present iff** `weight_type=ordinal` — `dominant`\|`major`\|`moderate`\|`minor`. **No fabricated %** (honest-weights). |
| `detail` | string | O | Human-readable, grounded in present numbers. |

> **Contract rule:** exactly one of (`weight`, `level`) is present, determined by `weight_type`. Enforced by
> schema `oneOf` + a guardrail. This encodes the honest-weights principle structurally.

## 5. `assets[]` — per-asset object (×6)

Two asset classes with slightly different shapes (challenge A8): **full assets** (BTC, ETH, GOLD, WTI,
USD_IRR) carry the full indicator suite; **index/context assets** (TOTAL_MCAP) carry a reduced set. The
`asset_class` + config drive which fields are required.

| Field | Type | Req? | Source | Notes |
|-------|------|------|--------|-------|
| `symbol` | enum **open** | M | system | `BTC`\|`ETH`\|`GOLD`\|`WTI`\|`USD_IRR`\|`TOTAL_MCAP` (open for future assets). |
| `asset_class` | enum closed | M | config | `crypto`\|`metal`\|`energy`\|`fx`\|`index`. Drives shape. |
| `price` | object | M | ingest | See §5.1. |
| `changes` | object | M | deterministic | `{ "6h","24h","7d","30d" }` as signed % (number). Missing horizon → declared in `data_gaps`. |
| `indicators` | object | C | deterministic | Full set for non-index; reduced for `index` (§5.2). |
| `scores` | object | M | mixed | See §5.3. |
| `market_health_index` | integer [0,100] | M | deterministic | Weighted projection (config weights). |
| `regime_sensitivity` | enum closed | M | config | `high`\|`medium`\|`low`. `low` for USD_IRR (ADR-005). |
| `activated_rules` | array\<RuleActivation\> | M (may be empty) | deterministic | See §5.4. |
| `causal_links` | array\<CausalLink\> | M (may be empty) | deterministic | See §5.5. Assembled only from rule edges. |
| `human_summary_fa` | string | C | **LLM** | **Persian only** (ADR-014). **Absent on Degraded Run.** Style guide X-6. |
| `novelty_flags` | array\<string\> (open vocab) | C | **LLM** | Absent/empty on Degraded Run. |
| `data_gaps` | array\<string\> (open vocab) | M (may be empty) | deterministic | Declared missing/excluded inputs. |

> **No `human_summary_en`** in v1.0.0 (ADR-014). **No `proxy_note`** field on USD_IRR (ADR-014 — proxy is
> internal-only).

### 5.1 `price`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `value` | number | M | For USD_IRR: **IRT (Toman)** value (ADR-014). |
| `currency` | enum open | M | `USD` \| `IRT`. USD_IRR → `"IRT"`. |
| `as_of` | string ISO-8601 | M | Price timestamp (USD_IRR may carry `+03:30`). |
| `is_stale` | boolean | M | Dim in UI when true (consumer obligation). |
| `stale_reason` | string (open vocab) | C | Present iff `is_stale`; e.g., `tehran_market_closed_weekend`. |
| `venue_aggregation` | string | C | Crypto only; e.g., `median_5` (ADR-009). |

### 5.2 `indicators`

- **Full assets** (`crypto`/`metal`/`energy`/`fx`): `rsi_14` (number 0–100), `macd_state`
  (enum closed: `bullish_cross`\|`bearish_cross`\|`neutral`\|`bullish`\|`bearish`), `ema_20_50`
  (enum closed: `above_diverging`\|`above_converging`\|`below_diverging`\|`below_converging`\|`crossing`),
  `atr_pct` (number ≥ 0), `volume_ratio_20d` (number ≥ 0).
- **Index assets** (`TOTAL_MCAP`): reduced set — `atr_pct` optional, plus `trend_state` (enum) and
  `dominance_shift` where applicable; **no full RSI/MACD/EMA required** (A8, avoids double-counting BTC).
  Exact reduced set fixed in the asset config contract.

### 5.3 `scores`

| Field | Type | Req? | Source | Notes |
|-------|------|------|--------|-------|
| `trend` | number [-1,1] | M | deterministic | — |
| `risk` | number [0,1] | M | deterministic | — |
| `sentiment` | number [-1,1] \| null | M,N | **LLM** | `null` when no eligible news exists or sentiment is degraded; never a fabricated 0. |
| `confidence` | number [0,1] | M | deterministic | System confidence for the asset read. |

### 5.4 `RuleActivation`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `rule_id` | string | M | References the rulebook. |
| `strength` | enum closed | M | `dominant`\|`major`\|`moderate`\|`minor`. |
| `horizon` | string | M | e.g., `24h`. |
| `decay_remaining` | number [0,1] | M | Remaining influence (half-life decay). |

### 5.5 `CausalLink`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `from` | string | M | Event/driver id (e.g., `us_cpi_2026_07`). |
| `to` | string (symbol) | M | Affected asset. |
| `direction` | enum closed | M | `bullish`\|`bearish`\|`neutral`. |
| `via_rule` | string | M | The rule that produced the edge; must exist in some asset's `activated_rules` (cross-check guardrail). |

## 6. `global`

| Field | Type | Req? | Source | Notes |
|-------|------|------|--------|-------|
| `fear_greed` | object `{value:int 0–100, label:enum}` | M | ingest | **Crypto-context input** (A6); label enum: `extreme_fear`…`extreme_greed`. |
| `btc_dominance` | number [0,100] | M | ingest | Fixed stablecoin methodology (ADR-009). |
| `total_market_cap_usd` | number ≥ 0 | M | ingest | Index/context series. |
| `expectation_context` | object \| null | M,N | system | **Reserved slot** — fed by event surprises now; `{recent_surprises:[{event, surprise_sigma}]}` shape. |
| `onchain_context` | null | M,N | — | **Reserved slot** — `null` in MVP (ADR-013). |

## 7. `guardrail_flags[]` — `Flag`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `code` | string (open vocab) | M | e.g., `degraded_run`, `summary_score_contradiction`, `source_deviation`, `stale_price`. |
| `severity` | enum closed | M | `info`\|`warning`\|`critical`. |
| `detail` | string | O | Human-readable context. |
| `field` | string | O | JSON path the flag refers to. |

## 8. Degraded-run shape (ADR-011) — normative

On a Degraded Run (`is_degraded=true`): all deterministic fields are present and valid; the **LLM-produced
fields are absent or null**:
- `assets[].human_summary_fa` — **absent**.
- `assets[].scores.sentiment` — **null**.
- `assets[].novelty_flags` — absent/empty.
- `regime.drivers` may lack `ordinal` (LLM) drivers but keeps `computed` ones.
- `guardrail_flags[]` includes `{code:"degraded_run", severity:"warning"}`.
A **degraded golden fixture** demonstrates this exact shape (§ fixtures spec).

## 9. Partial-degradation shape (ADR-011 DR-5)

If only synthesis failed (sentiment succeeded): `scores.sentiment` is present; `human_summary_fa` absent;
`is_degraded=true` with a flag scoped to synthesis. If only sentiment failed: `sentiment=null`,
`human_summary_fa` may still be present (synthesis ran on available data), `is_degraded=true`. The fixture set
covers at least the full-degraded case; partial cases are documented and contract-tested.

An asset with no fresh relevant news also has `sentiment=null`, but this normal no-evidence state does not by
itself set `is_degraded=true`. Absence of news is not automatically a `data_gaps` entry; that field remains for
missing, stale, or excluded expected inputs.

## 10. Field → need traceability (delta from Milestone 0 matrix)

The M0 traceability matrix already maps every field. **Deltas introduced/frozen at M2:**
- **Removed:** `human_summary_en` (never added — ADR-014).
- **Removed idea:** `proxy_note` / `rial_multiplier` (not in contract — ADR-014).
- **Added:** top-level `is_degraded` (serves P1/P2/P3 — degraded transparency; ADR-011); `versions.provider` +
  `versions.pricing` (serves P3 replay/cost; ADR-007).
- **Clarified:** `asset_class` drives full-vs-index indicator shape (A8).
The matrix is updated in lockstep (see §12 action).

## 11. Reconciliation with the §11.1 golden sample

The master-prompt §11.1 sample is **normative but illustrative**; these reconciliations are applied and will be
reflected in the golden fixture:
1. `USD_IRR.price.currency` → `"IRT"` (sample showed `IRR`); value expressed in Toman (ADR-014/D1).
2. No `human_summary_en` anywhere (ADR-014/O1).
3. No `proxy_note` on USD_IRR (ADR-014/D2).
4. Add top-level `is_degraded` (ADR-011) and `versions.provider`/`versions.pricing` (ADR-007).
5. `TOTAL_MCAP` uses the reduced indicator set (A8).
6. `fear_greed` documented as crypto-context, not a regime input (A6).
Everything else in the sample stands.

## 12. Actions this spec triggers (same-milestone, no divergence)

- Update [../product/05-traceability-matrix.md](../product/05-traceability-matrix.md) with the §10 deltas
  (add `is_degraded`, `versions.provider`, `versions.pricing`; confirm removals).
- Generate `schemas/market_state_run.v1.0.0.json` from this spec (post-approval).
- Produce golden fixtures: **normal** (all 6 assets) + **degraded** + **stale USD_IRR** (post-approval).
