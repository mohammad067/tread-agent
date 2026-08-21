# Configuration File Contracts

> **Milestone 2 — Contracts & Schemas.** Field-by-field specs for every versioned config file under `config/`.
> These are **data contracts** reviewed by non-engineers (Trader/PM) and validated on load. **Design document —
> no code, no actual YAML files** (generated after approval). Secrets are **never** in these files (ENV only).
> Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md); provider config
> governed by [../architecture/llm-provider-architecture.md](../architecture/llm-provider-architecture.md).
> **Version:** 1.0.0

## Principle
Adding an asset, changing a weight, swapping a provider, or tuning a half-life is a **config change with zero
code change** (F-8, ADR-007). Every file is SemVer-versioned; a snapshot (secrets redacted) is written to
`config_versions` and the version id recorded per Run.

---

## 1. `config/assets/{symbol}.yaml` — per-asset config (one file per asset)

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `symbol` | string | M | Matches the schema `symbol`. |
| `display_name` | string | M | e.g., `Bitcoin`. |
| `asset_class` | enum | M | `crypto`\|`metal`\|`energy`\|`fx`\|`index`. Drives indicator shape (A8). |
| `regime_sensitivity` | enum | M | `high`\|`medium`\|`low`. `low` for `usd_irr` (ADR-005). |
| `decimals` | integer | M | Display precision. |
| `trading_hours` | string/enum | M | `24/7`, `cme_wti`, `gold_spot`, `tehran_fx`, … (staleness logic). |
| `staleness_threshold_minutes` | integer | M | Older → `is_stale`. |
| `noise_threshold` | object | M | **ATR-relative** (A5): `{k: number, floor_pct: {6h,24h}}`. Trader-set. |
| `price_sources` | object | C | Crypto: `{aggregation: median, min_sources, max_deviation_pct}`. BTC/ETH target three configured sources and permit two only within the deviation threshold (ADR-009). |
| `indicators` | array\<enum\> | M | Full set for non-index; reduced for `index` (A8). |
| `rules_dir` | string | M | Path to the asset's rules (e.g., `rules/assets/btc/`). |
| `source` | object | C | e.g., `usd_irr`: `{provider: kifpool, field: priceSellIRT, currency: IRT}` (ADR-014). |

**Example intent (USD_IRR):** `asset_class: fx`, `regime_sensitivity: low`, `currency: IRT`,
`trading_hours: tehran_fx`, source = kifpool `priceSellIRT`. **No proxy field surfaced** (ADR-014).

## 2. `config/weights/mhi_weights.v1.yaml` — Market Health Index weights

| Field | Type | Notes |
|-------|------|-------|
| `version` | SemVer | Recorded per Run. |
| `weights` | map\<component, number\> | Components (trend/risk/sentiment/volatility/…) → weights summing to 1.0. |
| `per_asset_overrides` | map\<symbol, map\> | Optional class/asset-specific weight sets. |

**Invariant:** weights sum to 1.0 (validated on load); MHI = weighted projection → integer 0–100. Weights
**never** live in code or prompts (F-3).

## 3. `config/sources/source_quality.v1.yaml` — news source trust

| Field | Type | Notes |
|-------|------|-------|
| `version` | SemVer | — |
| `sources` | map\<source_id, number [0,1]\> | Source-quality factor for `effective_weight`. |
| `default_quality` | number [0,1] | For unlisted sources. |

## 4. `config/decay/half_lives.v1.yaml` — decay half-lives

| Field | Type | Notes |
|-------|------|-------|
| `version` | SemVer | — |
| `news_half_life_hours` | map\<event_type/category, number\> | Per-event-type recency decay for news. |
| `rule_half_life_defaults` | map\<event_type, number\> | Default rule half-lives (a rule may override). |
| `max_news_age_hours` | number > 0 | Hard eligibility window for ordinary News Items; initial value 36. Independent of event persistence. |

## 5. `config/models/providers.yaml` — provider config (frozen ADR-007 §3)

Full spec in [../architecture/llm-provider-architecture.md §3](../architecture/llm-provider-architecture.md).
Summary of the contract:

| Field | Type | Notes |
|-------|------|-------|
| `version` | SemVer | Recorded per Run. |
| `routing` | object | `{strategy: priority\|weighted, degrade_after_all_fail: true}` (**must stay true** — frozen). |
| `defaults` | object | temperature, max_tokens, timeout_seconds, retries, backoff, circuit_breaker. |
| `providers[]` | array | Per provider: `name`, `enabled`, `priority`, `weight`, `api_key_env` (**ENV name, not the key**), `models{sentiment,synthesis}`, overrides. |

**Invariant:** no secret values; `api_key_env` names an environment variable. Changing provider/model/routing
is config-only (frozen invariant #2/#3).

## 6. `config/models/pricing.v1.yaml` — cost price table (ADR-007 D-6)

| Field | Type | Notes |
|-------|------|-------|
| `version` | SemVer | Recorded per Run as `pricing_version`. |
| `prices` | map\<provider/model, {input_per_1k, output_per_1k, currency}\> | Drives `estimated_cost` per Call Record. |

Historical cost stays reproducible because the pricing version is pinned per Run.

## 7. `config/environments/{dev,staging,prod}.yaml` — non-secret env config

| Field | Type | Notes |
|-------|------|-------|
| `env` | enum | `dev`\|`staging`\|`prod`. |
| `database` | object | `{dialect: sqlite\|postgres, dsn_env: DB_DSN}` (DSN via ENV). |
| `ingestion` | object | `{mode: mock\|real}`. |
| `llm` | object | `{mode: mock\|deterministic\|real, providers_ref: providers.yaml}`. |
| `scheduler` | object | `{scheduled_cron: "0 */6 * * *", event_cooldown_minutes: 30}`. |
| `budget` | object | `{monthly_llm_budget, currency, alert_pct: 80}`. |

**No secrets** — DB DSN and API keys come from ENV (`dsn_env`, `api_key_env`). 12-factor (ADR-010).

## 8. Validation rules (all config, on load — M3)

1. Every file schema-validated on startup; malformed config **fails fast** (never mid-run).
2. `mhi_weights.weights` sum to 1.0.
3. `providers.yaml` contains no secret values; every `api_key_env`/`dsn_env` resolves at runtime or the
   provider is treated as disabled.
4. Adding `config/assets/{new}.yaml` + a `symbol` enum entry wires a new asset with **zero code change**
   (F-8) — contract test.
5. Every config version referenced by a Run resolves in `config_versions` (replay integrity).
