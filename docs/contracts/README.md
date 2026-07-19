# Contracts & Schemas — Milestone 2

> **Milestone 2 — Contracts & Schemas.** The complete contract **design** set: the public schema, internal
> DTOs, config contracts, rule schema, versioning strategy, and the OpenAPI/DB-migration/fixtures plan.
> **These are design documents. No implementation code, no schema/migration/fixture files yet** — those are
> generated from these specs after approval (per the user's "no code yet" instruction and §9's "schema files
> and migrations only").

## Documents

| # | Document | Covers |
|---|----------|--------|
| 1 | [versioning-strategy.md](versioning-strategy.md) | How every artifact is versioned, recorded per Run, and evolved (SemVer, open/closed enums, prompt `vN#hash`). |
| 2 | [market-state-run-schema.md](market-state-run-schema.md) | **The public contract** — field-by-field `MarketStateRun v1.0.0` (FA-only, IRT, index assets, reserved slots, degraded shape). |
| 3 | [internal-dtos.md](internal-dtos.md) | `RawSnapshot`, `FeatureSet`, `NewsDigest`, `ReasoningRequest/Response`, `StateVector`, `RuleActivation`, `CausalLink`, `CallRecord`, `DegradedMarker`. |
| 4 | [config-contracts.md](config-contracts.md) | Per-asset config, MHI weights, source quality, half-lives, `providers.yaml`, pricing, environments. |
| 5 | [rule-schema.md](rule-schema.md) | Rule YAML contract + hard sign-off gate + regime guards + conflict handling. |
| 6 | [api-db-fixtures.md](api-db-fixtures.md) | OpenAPI outline, Alembic migration plan, golden-fixtures spec. |

## Decisions baked into these contracts (all resolved)

- **FA-only summary** (`human_summary_fa`, no `human_summary_en`) — ADR-014.
- **USD/IRR in IRT (Toman)**, `currency:"IRT"`, no Rial field, **no proxy label** — ADR-014.
- **Provider-agnostic** DTOs (`ReasoningRequest/Response` neutral; `CallRecord` for replay/cost) — ADR-007.
- **Degraded run** shape (LLM fields absent/null, `is_degraded`) — ADR-011.
- **Index assets** (TOTAL_MCAP reduced indicators) — A8.
- **Deterministic regime confidence**, honest `computed` vs `ordinal` weights — A2/§7.
- **Reserved slots** (`expectation_context` surprise-fed, `onchain_context` null) — ADR-013.

## New schema fields introduced at M2 (traceability updated in lockstep)

`is_degraded`, `versions.provider`, `versions.pricing`, `asset_class` — all added to
[../product/05-traceability-matrix.md](../product/05-traceability-matrix.md) in the same milestone (no
divergence, §8).

## What gets generated after approval

The seven artifact groups in [api-db-fixtures.md §D](api-db-fixtures.md): the public + internal JSON Schemas,
the rule schema, `openapi.yaml`, the `0001_initial` migration, golden fixtures, and config schemas.

## Open items still gating later milestones (not M2 blockers)

- **OQ-3** rule conflict-resolution policy (Trader) — blocks M3 RuleEngine.
- **OQ-5** crypto venue list + dominance stablecoin methodology (Blockchain) — blocks M3 ingestion.
- **OQ-6** news relevance signal definition — blocks M3 NewsWeigher.
- **OQ-9** ATR-relative noise `k` per asset (Trader) — blocks M6 evaluation.

(O1/D1/D2 are **resolved**; see [ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md).)
