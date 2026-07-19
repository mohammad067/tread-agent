# Database Architecture

> **Milestone 1.** Database architecture, ER diagram, and **all tables**. Design only — **no SQL, no DDL, no
> migrations code** (those are Milestone 2). Terms binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md). Storage choice: **[ADR-006](../adr/ADR-006-storage-choice.md)**.
> **Version:** 1.0.0

## 1. Storage strategy: SQLite → Postgres (one codebase)

- **dev:** SQLite (file-based, zero-ops, hermetic CI).
- **staging/prod:** PostgreSQL 16.
- **One SQLAlchemy codebase**, dialect-neutral SQL, Alembic migrations. **Rationale:** challenge A1 — MVP write
  volume is ~4 runs/day; SQLite is ample for dev and keeps the loop simple, while the Postgres path is open
  from day one without a rewrite. **Cons:** must avoid dialect-specific features (e.g., use a portable JSON
  column strategy — `JSON` on SQLite, `JSONB` on Postgres via SQLAlchemy type variants). **Alternatives
  rejected:** Postgres-everywhere (heavier dev/CI); NoSQL (loses relational joins across runs/outcomes/
  versions that evaluation depends on).

## 2. Design principles

1. **Immutability where replay depends on it.** `run_inputs`, `run_outputs`, and `call_records` are
   **append-only**; never `UPDATE`d. Corrections create new runs, never rewrite history (ADR-004).
2. **Everything versioned.** Every run records the exact `rulebook`, `mhi_weights`, `prompt_*`, `provider`,
   `model`, `pipeline`, and `pricing` versions used (release policy + frozen replay requirements).
3. **Snapshots stored verbatim.** Raw ingested inputs are stored as JSON exactly as received, plus a content
   hash, so replay feeds byte-identical inputs.
4. **Separation of concerns in tables.** Identity/metadata (`runs`) is separate from immutable inputs
   (`run_inputs`), immutable outputs (`run_outputs`), and post-hoc outcomes (`outcomes`) — so each has its own
   lifecycle and write pattern.
5. **`run_id` is a ULID** (sortable, unique) and the correlation key across every table and every log line.

## 3. ER diagram

```mermaid
erDiagram
  RUNS ||--|| RUN_INPUTS : "has (1:1 immutable snapshot)"
  RUNS ||--|| RUN_OUTPUTS : "has (1:1 immutable output)"
  RUNS ||--o{ OUTCOMES : "accrues (0..n at +6h/+24h)"
  RUNS ||--o{ CALL_RECORDS : "made (0..n LLM attempts)"
  RUNS }o--|| CONFIG_VERSIONS : "used"
  RUNS }o--|| RULES_VERSIONS : "used"
  RUNS }o--o{ MACRO_EVENTS : "triggered_by / referenced"
  RUN_INPUTS }o--o{ NEWS_ITEMS : "snapshots (by reference + embedded)"
  EVALUATION_REPORTS }o--o{ RUNS : "aggregates range"

  RUNS {
    ulid run_id PK
    bigint run_sequence
    string trigger_type
    json   trigger_detail
    timestamptz generated_at
    string schema_version
    string pipeline_version
    string provider_version
    string model_version
    string prompt_sentiment_version
    string prompt_synthesis_version
    string rulebook_version FK
    string mhi_weights_version
    string pricing_version
    string status
    bool   is_degraded
  }
  RUN_INPUTS {
    ulid run_id PK_FK
    json  raw_snapshots
    string snapshot_hash
    json  data_gaps
    json  deviation_flags
    timestamptz ingested_at
  }
  RUN_OUTPUTS {
    ulid run_id PK_FK
    json  market_state_run
    json  guardrail_flags
    string output_hash
    timestamptz persisted_at
  }
  OUTCOMES {
    ulid outcome_id PK
    ulid run_id FK
    string symbol
    string horizon
    float  realized_return_pct
    float  realized_volatility
    float  noise_threshold_pct
    string outcome_label
    timestamptz recorded_at
  }
  CALL_RECORDS {
    ulid call_id PK
    ulid run_id FK
    string llm_job
    int    attempt_index
    string provider
    string model_id
    string prompt_version
    string prompt_hash
    text   rendered_prompt
    json   response
    string response_hash
    int    latency_ms
    int    input_tokens
    int    output_tokens
    float  estimated_cost
    int    retries
    string finish_reason
    string outcome
    timestamptz created_at
  }
  RULES_VERSIONS {
    string rulebook_version PK
    json   rules_snapshot
    string content_hash
    string reviewed_by
    timestamptz created_at
  }
  CONFIG_VERSIONS {
    string config_bundle_version PK
    json   config_snapshot
    string content_hash
    timestamptz created_at
  }
  NEWS_ITEMS {
    ulid news_id PK
    string source
    string url
    text   title
    timestamptz published_at
    float  source_quality
    json   raw
    timestamptz ingested_at
  }
  MACRO_EVENTS {
    string event_id PK
    string event_type
    timestamptz scheduled_at
    float  consensus
    float  actual
    float  surprise
    string entered_by
    timestamptz recorded_at
  }
  EVALUATION_REPORTS {
    string report_id PK
    string period
    json   metrics
    json   ablation_results
    json   decision_rule_status
    timestamptz generated_at
  }
```

## 4. Table catalog (all tables)

> Types shown as portable intent (`ulid`, `json`, `timestamptz`, `text`). Concrete column types and
> constraints are finalized in Milestone 2 migrations.

### 4.1 `runs` — run identity & versions (mutable status only)
- **Purpose:** One row per Run; identity, trigger, timestamps, and the **exact versions** used.
- **Key fields:** `run_id` (ULID PK), `run_sequence`, `trigger_type` (`scheduled`|`event`), `trigger_detail`
  (JSON: `event_id`, `debounced_events`), `generated_at`, all `*_version` columns (schema, pipeline,
  **provider**, **model**, prompt_sentiment, prompt_synthesis, rulebook, mhi_weights, pricing), `status`
  (`published`|`degraded`|`failed`), `is_degraded`.
- **Write pattern:** insert once; only `status`/`is_degraded` may update within the same run transaction.
- **Indexes:** `run_sequence`, `generated_at`, `trigger_type`.

### 4.2 `run_inputs` — immutable input snapshot (1:1)
- **Purpose:** The exact raw inputs the Run saw, for byte-identical replay.
- **Key fields:** `run_id` (PK/FK), `raw_snapshots` (JSON — all ingested price/indicator/F&G/dominance/event/
  news snapshots verbatim), `snapshot_hash`, `data_gaps` (JSON), `deviation_flags` (JSON, ADR-009),
  `ingested_at`.
- **Write pattern:** **append-only**, never updated.

### 4.3 `run_outputs` — immutable output (1:1)
- **Purpose:** The full `MarketStateRun` JSON produced, plus guardrail flags and a hash.
- **Key fields:** `run_id` (PK/FK), `market_state_run` (JSON — the schema-valid payload), `guardrail_flags`
  (JSON), `output_hash`, `persisted_at`.
- **Write pattern:** **append-only**.

### 4.4 `outcomes` — realized results (0..n, post-hoc)
- **Purpose:** OutcomeRecorder attaches realized returns/volatility at +6h/+24h.
- **Key fields:** `outcome_id` (PK), `run_id` (FK), `symbol`, `horizon` (`6h`|`24h`), `realized_return_pct`,
  `realized_volatility`, `noise_threshold_pct` (**ATR-relative**, A5), `outcome_label`
  (`up`|`down`|`noise`), `recorded_at`.
- **Write pattern:** insert when the horizon matures; one row per (run, symbol, horizon).

### 4.5 `call_records` — per-LLM-attempt replay/cost/metrics unit (0..n)
- **Purpose:** Every External LLM Provider attempt, for lossless replay + automatic cost + metrics
  (frozen ADR-007 D-6). Fields per [llm-provider-architecture.md §5](llm-provider-architecture.md).
- **Key fields:** `call_id` (PK), `run_id` (FK), `llm_job` (`sentiment`|`synthesis`), `attempt_index`,
  `provider`, `model_id`, `prompt_version`, `prompt_hash`, `rendered_prompt`, `response` (JSON),
  `response_hash`, `latency_ms`, `input_tokens`, `output_tokens`, `estimated_cost`, `retries`,
  `finish_reason`, `outcome` (`success`|`timeout`|`error`|`circuit_open`), `created_at`.
- **Write pattern:** **append-only**, one row per attempt (including failed attempts, for failover audit).
- **Indexes:** `run_id`, `provider`, `created_at`.

### 4.6 `rules_versions` — rulebook snapshots
- **Purpose:** The exact rulebook (all YAML) at each version, for replay + audit + Trader sign-off record.
- **Key fields:** `rulebook_version` (PK, SemVer), `rules_snapshot` (JSON), `content_hash`, `reviewed_by`,
  `created_at`.
- **Write pattern:** insert on any rule change (bumped version).

### 4.7 `config_versions` — config bundle snapshots
- **Purpose:** The exact config bundle (asset configs, MHI weights, source-quality, half-lives, providers.yaml
  **without secrets**, pricing) per version.
- **Key fields:** `config_bundle_version` (PK), `config_snapshot` (JSON, secrets redacted), `content_hash`,
  `created_at`.

### 4.8 `news_items` — ingested news feed records
- **Purpose:** The pre-collected news the system consumed (Q3), referenced by `run_inputs` snapshots.
- **Key fields:** `news_id` (PK), `source`, `url`, `title`, `published_at`, `source_quality`, `raw` (JSON),
  `ingested_at`.

### 4.9 `macro_events` — manually entered events (Q4)
- **Purpose:** CPI/FOMC/NFP-class events with consensus/actual → surprise, driving the event path + rules.
- **Key fields:** `event_id` (PK), `event_type` (`us_cpi`|`fomc`|`us_nfp`|…), `scheduled_at`, `consensus`,
  `actual`, `surprise` (computed = actual − consensus), `entered_by`, `recorded_at`.

### 4.10 `evaluation_reports` — monthly/periodic reports
- **Purpose:** Persisted evaluation outputs (§11.6): coverage, accuracy vs baselines, Brier, calibration,
  ablation A–D, decision-rule status, cost/latency, rule performance.
- **Key fields:** `report_id` (PK), `period`, `metrics` (JSON), `ablation_results` (JSON),
  `decision_rule_status` (JSON), `generated_at`.

## 5. How the schema guarantees replay (the load-bearing property)

A Run is reproducible because, together, these are stored immutably: **inputs** (`run_inputs.raw_snapshots`),
**exact LLM calls** (`call_records.rendered_prompt` + `response`), and **every version** (`runs.*_version` +
`rules_versions` + `config_versions`). `ReplayProvider` replays `call_records`; the deterministic core recomputes
from `run_inputs`; both must reproduce `run_outputs.market_state_run` byte-identically for the deterministic
fields (nightly replay regression, §12).

## 6. Retention, backup, DR (staged per A1)

- **Event log tables (`run_inputs`, `run_outputs`, `call_records`) are append-only and in every backup** —
  losing them destroys replayability, which destroys the product (§12).
- Postgres nightly dumps, 30-day retention, RPO 24h / RTO 4h, restore rehearsed once before M7 sign-off (§12).
- SQLite (dev) is disposable; no DR.

## 7. Trade-offs & alternatives (summary)

- **JSON columns for snapshots/outputs** vs. fully normalized columns: chosen JSON because the payloads are
  contract-shaped documents whose schema is versioned separately; normalizing every field would couple the DB
  to the JSON Schema and require a migration per schema change. **Con:** less queryable inside SQL — acceptable
  because evaluation reads whole documents, and indexed metadata lives in typed columns.
- **Separate `call_records` table** vs. embedding calls in `run_outputs`: chosen separate for per-attempt
  granularity (failover audit, cost/metrics) and append-only cleanliness.
- **ULID** vs. UUID/auto-increment: ULID is sortable (good for `run_sequence` correlation and time-ordering)
  and globally unique (idempotency across restarts).
