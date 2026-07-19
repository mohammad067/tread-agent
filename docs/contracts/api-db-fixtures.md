# OpenAPI Outline, DB Migration Plan & Golden Fixtures Spec

> **Milestone 2 — Contracts & Schemas.** Three contract artifacts: the OpenAPI outline (external API contract),
> the database migration plan (schema realization), and the golden-fixtures spec (normative examples).
> **Design document — no code, no `openapi.yaml`, no migration files, no fixture JSON.** These are generated
> after approval. Builds on [../architecture/api-design.md](../architecture/api-design.md) and
> [../architecture/database.md](../architecture/database.md).
> **Version:** 1.0.0

---

# Part A — OpenAPI outline (`docs/api/openapi.yaml`, generated post-approval)

## A.1 Info & servers
- `openapi: 3.1`, `info.version: v1`, title "Market State Engine API".
- Security scheme: `ApiKeyAuth` (header). Two scopes: **read**, **write**.
- Every response references the **envelope** (`data` + `meta`) and the shared `Error` schema.

## A.2 Paths (from the endpoint catalog — API-only, no UI)

| Path | Method | Request | Response `data` | Auth |
|------|--------|---------|-----------------|------|
| `/v1/state/latest` | GET | — | `MarketStateRun` | read |
| `/v1/runs/{run_id}` | GET | path `run_id` | `MarketStateRun` | read |
| `/v1/runs` | GET | query `from,to,trigger_type,limit,cursor` | `MarketStateRun[]` (paginated) | read |
| `/v1/runs/{run_id}/inputs` | GET | path | `RunInputs` (immutable snapshot) | read |
| `/v1/runs/{run_id}/calls` | GET | path | `CallRecord[]` | read |
| `/v1/evaluation/summary` | GET | query `period` | `EvaluationSummary` | read |
| `/v1/evaluation/reports/{report_id}` | GET | path | `EvaluationReport` | read |
| `/v1/health` | GET | — | `Health` | none/read |
| `/v1/meta/versions` | GET | — | `ActiveVersions` | read |
| `/v1/events` | POST | `MacroEventInput` | `{event_id, accepted, debounced}` | **write** |
| `/v1/runs:trigger` | POST | `{reason}` | `{run_id, status}` | **write** |

## A.3 Components (schemas referenced)
- `MarketStateRun` → the public schema ([market-state-run-schema.md](market-state-run-schema.md)).
- `Envelope`, `Meta` (api_version, schema_version, next_scheduled_run, disclaimer, is_degraded, pagination).
- `Error` (code, message, correlation_id, details).
- `MacroEventInput` (event_type, scheduled_at, consensus, actual — **surprise computed server-side**, never
  trusted from client).
- `RunInputs`, `CallRecord`, `EvaluationSummary`, `EvaluationReport`, `Health`, `ActiveVersions`.

## A.4 Contract-test hooks
- Schemathesis runs the OpenAPI against the live app (M5) — every response must validate.
- `MarketStateRun` responses additionally validate against `schemas/market_state_run.v1.0.0.json` (defense in
  depth: OpenAPI ref + standalone JSON Schema).

---

# Part B — Database migration plan (Alembic, generated post-approval)

## B.1 Migration `0001_initial` — all MVP tables
Creates every table from [../architecture/database.md](../architecture/database.md): `runs`, `run_inputs`,
`run_outputs`, `outcomes`, `call_records`, `rules_versions`, `config_versions`, `news_items`, `macro_events`,
`evaluation_reports`. Includes the **M2 field additions**:
- `runs.is_degraded` (boolean, not null, default false),
- `runs.provider_version`, `runs.model_version`, `runs.pricing_version` (nullable strings).

## B.2 Portability (SQLite ↔ Postgres — ADR-006)
- JSON columns use a **dialect-variant type** (`JSON` on SQLite, `JSONB` on Postgres) via one SQLAlchemy type.
- No dialect-specific SQL; ULIDs stored as `CHAR(26)`/text; timestamps as timezone-aware.
- Append-only tables (`run_inputs`, `run_outputs`, `call_records`) have **no UPDATE path** in the ORM layer
  (enforced at repository level, not just convention).

## B.3 Indexes (from the DB design)
`runs(run_sequence)`, `runs(generated_at)`, `runs(trigger_type)`, `call_records(run_id)`,
`call_records(provider, created_at)`, `outcomes(run_id, symbol, horizon)`, `macro_events(event_type,
scheduled_at)`.

## B.4 Migration discipline
- One migration per schema change; additive/backfilled/nullable to keep the SQLite↔Postgres path clean.
- Migrations reviewed like code; a schema change that breaks a golden fixture is a **contract change**
  (release policy).

---

# Part C — Golden fixtures spec (`tests/golden/`, generated post-approval)

The golden fixtures are **normative** (master-prompt §11): schema-validated, Trader-reviewed for realism, and
any future change that breaks them is a reviewed contract change.

## C.1 Fixture set (minimum)

| Fixture | Purpose | Must show |
|---------|---------|-----------|
| `market_state_run.normal.json` | The happy path | All **6 assets**; regime with computed+ordinal drivers; activated rules + causal links; `human_summary_fa` present; `is_degraded=false`. |
| `market_state_run.degraded.json` | Full LLM outage (ADR-011) | `is_degraded=true`; `scores.sentiment=null`; `human_summary_fa` **absent**; `guardrail_flags` has `degraded_run`; deterministic fields intact. |
| `market_state_run.stale_usdirr.json` | Tehran market closed (UC-4) | `USD_IRR.price.is_stale=true` + `stale_reason`; `currency:"IRT"`; `data_gaps` includes the informal-quotes exclusion; **no proxy label** (ADR-014). |
| `rule.cpi_hot.corrected.yaml` | Rule schema (A4 fix) | Regime-guarded or `minor`+`uncertain` gold effect; `economic_rationale` + `reviewed_by: senior_trader`. |
| `reasoning_request.sentiment.json` / `.synthesis.json` | DTO contracts | `language:"fa"`, grounding constraint, neutral (no vendor fields). |
| `call_record.example.json` | Replay/cost unit | All fields incl. prompt/response hashes, tokens, estimated_cost, finish_reason, outcome. |

## C.2 Realism review (Senior Trader persona)
Every `MarketStateRun` fixture is reviewed for **market realism** — "an output a desk trader would laugh at is
a defect." The normal fixture's numbers (CPI surprise → risk-off, BTC pressure, gold regime-conditioned) must
be defensible. Recorded as a manual-test note (M-105 family).

## C.3 Fixture invariants (contract tests)
1. Every `MarketStateRun` fixture validates against `schemas/market_state_run.v1.0.0.json`.
2. The degraded fixture has **no** LLM-only fields populated (honest absence).
3. Every `causal_links[].via_rule` resolves to an `activated_rules[].rule_id` in the same fixture.
4. USD_IRR fixtures use `currency:"IRT"` and carry **no** proxy/`rial_multiplier` fields (ADR-014).
5. Fixtures are the inputs to replay regression (M6) — they must round-trip through the deterministic core
   unchanged.

---

## D. What M2 generates after approval (the "schema files and migrations only" of §9)

1. `schemas/market_state_run.v1.0.0.json` (from [market-state-run-schema.md](market-state-run-schema.md)).
2. `schemas/internal/{reasoning_request,reasoning_response,news_digest,rule_activation,call_record,feature_set}.v1.json`.
3. `schemas/internal/rule.v1.json` (from [rule-schema.md](rule-schema.md)).
4. `docs/api/openapi.yaml` (from Part A).
5. Alembic `0001_initial` migration (from Part B).
6. Golden fixtures (from Part C).
7. Config file schemas for `config/**` (from [config-contracts.md](config-contracts.md)).

> These are the schema/migration/fixture artifacts the master prompt scopes to Milestone 2. They are held
> until you approve this design set, per your "no implementation code yet" instruction.
