# API Design

> **Milestone 1.** API-first design, endpoint catalog, response envelope, versioning, auth, rate limiting, and
> the error contract. **Design only — no code, no OpenAPI file** (the OpenAPI spec is a Milestone 2
> deliverable). The system is **API-only with no front-end** ([ADR-012](../adr/ADR-012-api-only-no-frontend.md)).
> Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> **Version:** 1.0.0

## 1. API-first principles

1. **The JSON contract is the product.** With no UI, the REST API + `MarketStateRun` schema is the entire
   consumer surface. Every field must trace to a need (traceability matrix); every response is schema-valid.
2. **Read-optimized.** Consumers read Market States; they do not create them (runs come from the Scheduler/
   event path). The public API is **read-only** except for two guarded operational endpoints (event ingestion
   + manual run trigger) behind the static API key.
3. **Stable & versioned.** Path-versioned (`/v1/…`); breaking changes → `/v2` with a deprecation window
   (release policy). Schema version travels in the payload (`schema_version`) and envelope (`meta.api_version`).
4. **Envelope + disclaimer everywhere.** Every response wraps `data` in a `meta` envelope carrying
   `api_version`, `next_scheduled_run`, and the **disclaimer** (compliance C-2).
5. **Honest degraded shape.** Degraded Runs are returned with the same schema, LLM fields explicitly absent and
   flagged — never fabricated (ADR-011). A **degraded golden fixture** (M2) lets integrators code for it.

## 2. Endpoint catalog

| Method | Path | Purpose | Auth | Persona | Idempotent |
|--------|------|---------|------|---------|-----------|
| GET | `/v1/state/latest` | Latest `MarketStateRun` (+ meta) | key | P1, P4 | yes |
| GET | `/v1/runs/{run_id}` | A specific Run by ULID | key | P1, P2, P3 | yes |
| GET | `/v1/runs?from=&to=&trigger_type=&limit=&cursor=` | Run range, filterable by time + `trigger_type`, paginated | key | P2, P3 | yes |
| GET | `/v1/runs/{run_id}/inputs` | Immutable input snapshot for a Run (audit/replay) | key | P3 | yes |
| GET | `/v1/runs/{run_id}/calls` | Call Records for a Run (provider/model/hashes/tokens/cost) | key | P3 | yes |
| GET | `/v1/evaluation/summary?period=` | Evaluation metrics (accuracy vs baselines, Brier, calibration, ablation) | key | P3, P4 | yes |
| GET | `/v1/evaluation/reports/{report_id}` | A persisted monthly report | key | P3 | yes |
| GET | `/v1/health` | Liveness + `next_scheduled_run` + last-run freshness | none/key | ops, P2 | yes |
| GET | `/v1/meta/versions` | Current active versions (schema/rulebook/weights/prompts/provider/model/pipeline) | key | P2, P3 | yes |
| POST | `/v1/events` | **Operational:** submit a manually-entered Macro Event (consensus/actual) → may trigger the event path | key (write) | operator (Q4) | by `event_id` |
| POST | `/v1/runs:trigger` | **Operational:** manually trigger a run (respects debounce) | key (write) | operator | by dedupe window |

> **Why include `POST /v1/events`:** Q4 fixed macro events as **manual entry**; the event-trigger path needs an
> ingestion surface. It is guarded, idempotent by `event_id`, and is the *only* way surprises enter the system.
> **Why `runs:trigger`:** operational recovery/testing (e.g., re-run after a fixed data source); respects the
> same debounce/idempotency as the scheduler. Both are **operational**, not consumer-facing analytics.

## 3. Response envelope (shape, not code)

Every successful response:

```
{
  "data":  <resource>,               // e.g., a MarketStateRun (v1.0.0) or a list
  "meta": {
    "api_version": "v1",
    "schema_version": "1.0.0",       // for payloads that carry the market-state schema
    "next_scheduled_run": "<iso8601>",
    "disclaimer": "Market observation only. Not investment advice.",
    "is_degraded": <bool>,           // surfaced for state payloads
    "pagination": { "next_cursor": "<opaque|null>", "limit": <int> }   // list endpoints only
  }
}
```

**Rationale:** a uniform envelope lets P2 write one response handler; `meta` carries compliance + freshness +
pagination without polluting the domain payload. **Alternative rejected:** bare payloads (no envelope) — would
force the disclaimer into every schema and lose a place for pagination/freshness metadata.

## 4. Versioning & compatibility

- **Path version** `/v1` is the compatibility boundary; **`schema_version`** in the payload is the contract
  version. Additive schema changes are MINOR (no path bump); breaking changes → `/v2` + deprecation window
  (release policy §4–5).
- `GET /v1/meta/versions` exposes all active artifact versions so integrators + evaluators can pin behavior.

## 5. Authentication & authorization

- **Static API key** on all endpoints except `/v1/health` (liveness may be open or key-gated per environment)
  — full auth is a non-goal (§3). Key supplied via header; validated by middleware.
- **Two key scopes** (minimal): **read** (all GETs) and **write** (`POST /v1/events`, `POST /v1/runs:trigger`).
  Write endpoints are operational and separately keyed so a leaked read key can't inject events.
- Keys come from **environment/secret store only**, never config or logs (§12 security).
- **No user accounts, no multi-tenancy** (§3).

## 6. Rate limiting

- **Token-bucket rate limit** on the public API (per key, per endpoint class). Reads: generous; writes: strict.
- Staged per challenge A1: the limiter is a **Milestone 5** hardening item; the design slot exists now so it's
  not retrofitted. **429** with `Retry-After` on breach.

## 7. Error contract (uniform, typed)

All errors return a consistent shape (HTTP status + machine code + message + `run_id`/correlation where
relevant):

```
{
  "error": {
    "code": "not_found | invalid_request | unauthorized | forbidden | rate_limited | conflict | unavailable | internal",
    "message": "<human-readable, no secrets, no PII>",
    "correlation_id": "<request id>",
    "details": { ... optional field-level validation errors ... }
  }
}
```

| Situation | HTTP | `code` |
|-----------|------|--------|
| Unknown `run_id`/report | 404 | `not_found` |
| Bad query params / body fails validation | 422 | `invalid_request` |
| Missing/invalid API key | 401 | `unauthorized` |
| Read key on a write endpoint | 403 | `forbidden` |
| Duplicate `event_id` / re-trigger of existing run | 200 (idempotent no-op) or 409 | `conflict` |
| Rate limit exceeded | 429 | `rate_limited` |
| Dependency down (DB) | 503 | `unavailable` |
| Unexpected | 500 | `internal` |

**Note:** an LLM provider outage is **never** an API error — it produces a **Degraded Run** that returns 200
with `meta.is_degraded=true` (ADR-011). The API's availability does not depend on any external provider.

## 8. SLOs (from §12, surfaced in the API design)

- `GET /v1/state/latest` **p95 ≤ 300 ms** (reads a persisted document; no computation on the request path).
- Availability target **99.5%**; `/v1/health` supports missed-run detection (no run within 6h+15min → alert).

## 9. What the API deliberately does not do

- No computation on the request path (all market numbers are precomputed by the pipeline and persisted).
- No advice, recommendations, or predictions in any field (compliance).
- No streaming, websockets, or long-polling (§3) — freshness is via `next_scheduled_run` + polling.
- No front-end assets, HTML, or server-rendered views (ADR-012).

## 10. Consumer-facing UX obligations (contract, not UI we build)

Because there is no front-end, the Milestone 0 **UX & content requirements**
([../product/06-ux-content-requirements.md](../product/06-ux-content-requirements.md)) become **binding
obligations on API consumers**, communicated via the schema + docs: dim stale prices (`is_stale`), distinguish
`computed` vs `ordinal` weights, label `confidence` as "system confidence," show the disclaimer, mark degraded
runs. The API guarantees the *data and flags* needed to honor them; honoring them in a UI is the consumer's
responsibility ([ADR-012](../adr/ADR-012-api-only-no-frontend.md)).
