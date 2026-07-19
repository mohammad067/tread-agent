# Versioning Strategy

> **Milestone 2 — Contracts & Schemas.** How every independently-changeable artifact is versioned, recorded
> per Run, and evolved. **Design document — no code, no schema files.** The actual `schemas/*.json`,
> migrations, and fixtures are generated after this design is approved. Terms binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md). Consumer-facing rules per
> [../product/10-release-policy.md](../product/10-release-policy.md).
> **Version:** 1.0.0

## 1. The versioned artifacts (and where each is recorded)

Every artifact that can change independently carries its own version, and **every Run records the exact
version of each** in the `runs.*_version` columns ([../architecture/database.md](../architecture/database.md)).
This is what makes replay reproducible and audits precise.

| Artifact | Scheme | Version token | Recorded in Run as | Snapshot table |
|----------|--------|---------------|--------------------|----------------|
| **MarketStateRun JSON Schema** | SemVer `MAJOR.MINOR.PATCH` | `1.0.0` | `schema_version` | (schema file in `schemas/`) |
| **Internal DTO schemas** | SemVer per DTO | `v1` (+ file hash) | via `pipeline_version` | `schemas/internal/` |
| **Rulebook** | SemVer | `1.4.0` | `rulebook_version` | `rules_versions` |
| **MHI weights** | SemVer | `1.1.0` | `mhi_weights_version` | `config_versions` |
| **Prompt (sentiment)** | `vN#hash` | `v1#a3f9c2` | `prompt_sentiment_version` | `config_versions` (+ `prompts/`) |
| **Prompt (synthesis)** | `vN#hash` | `v1#7be014` | `prompt_synthesis_version` | `config_versions` |
| **Provider** | vendor id | `openai` | `provider_version` | Call Records |
| **Model** | model id | `gpt-5.5` | `model_version` | Call Records |
| **Pricing table** | SemVer | `1.0.0` | `pricing_version` | `config_versions` |
| **Config bundle** (assets, sources, decay, envs) | SemVer | `1.0.0` | (rolled into `config_versions`) | `config_versions` |
| **Pipeline** (code) | SemVer via git tag | `0.9.2` | `pipeline_version` | — |

> **Design rule:** the set of `*_version` fields in `runs` **is** the reproducibility contract. Adding a new
> versioned artifact means adding a `*_version` column (a migration) — never an untracked global.

## 2. SemVer semantics for the public schema (the consumer contract)

Restated from the release policy so the schema design obeys it exactly:

- **MAJOR** — breaking: field removed, renamed, type narrowed, enum value removed, a field made required that
  consumers didn't send/receive before, or a unit/semantic change (e.g., switching `USD_IRR` away from IRT).
- **MINOR** — additive/backward-compatible: a new **optional** field, a new value in an **open** enum, filling
  a reserved `null` slot (e.g., `onchain_context`), **adding `human_summary_en`** later (ADR-014's forward
  path).
- **PATCH** — non-structural: description/constraint clarifications that don't change validation outcomes for
  existing valid documents.

**v1.0.0 freeze consequence:** because O1/D1/D2 are resolved *before* the freeze (ADR-014), the MVP ships a
clean v1.0.0 with no early MAJOR. The only anticipated near-term evolution (EN summary) is a MINOR.

## 3. Open vs. closed enums (a deliberate design choice)

To keep additive evolution MINOR, the schema classifies each enum:

| Enum | Open/Closed | Why |
|------|-------------|-----|
| `regime.state` | **Closed** (4 values) | The regime taxonomy is a deliberate, Trader-reviewed set; adding a state is a semantic change → MAJOR-worthy review. |
| `trigger_type` | **Closed** (`scheduled`,`event`) | Core evaluation bucket; changing it changes metrics semantics. |
| `symbol` | **Open** | Adding an asset = one config file (F-8); a new symbol is additive (MINOR). |
| `activated_rules[].strength`, driver `level` | **Closed** (`dominant/major/moderate/minor`) | Ordinal scale is fixed; honest-weights contract depends on it. |
| `direction` | **Closed** (`bullish/bearish/neutral`) | Fixed causal vocabulary. |
| `macd_state`, `ema_20_50` | **Closed** | Indicator semantics are fixed math outputs. |
| `data_gaps[]`, `novelty_flags[]`, `guardrail_flags[]` codes | **Open** (controlled vocabulary) | New gap/flag types appear as the system matures; additive. |
| `stale_reason` | **Open** | New staleness causes may appear. |

**Design consequence:** open enums are validated against a *documented controlled vocabulary* (not `enum` in
JSON Schema, but a `pattern`/registry), so adding a value doesn't bump MAJOR; closed enums use hard `enum`.

## 4. Prompt versioning (`vN#hash`)

- **`vN`** — human-authored template version (`prompts/sentiment/v1.md`).
- **`#hash`** — content hash of the **rendered neutral prompt** (frozen invariant #4), so the same request
  yields the same hash across vendors and any template edit changes the hash visibly.
- Recorded per Run **and** per Call Record. A prompt edit is a **versioned event** (changelog + golden prompt
  test diff).

## 5. Config & rulebook versioning

- Each config/rule change bumps its SemVer and writes a **full snapshot** (secrets redacted) to
  `config_versions` / `rules_versions`. The Run stores the version id.
- **Rulebook** additionally requires the `economic_rationale` diff + Trader sign-off in the PR (ADR-008, §12).
- **Replay** loads the exact snapshot by version, so a run replays under the rules/weights it actually used —
  not today's.

## 6. Compatibility & migration rules (schema evolution)

| Change | Version impact | Migration/notice |
|--------|----------------|------------------|
| Add optional field (e.g., `human_summary_en`) | MINOR | changelog + release note; no consumer action required |
| Fill reserved slot (`onchain_context`, `expectation_context` growth) | MINOR | changelog; documented shape |
| Add asset symbol | MINOR | new config file; symbol enum is open |
| Add `data_gap`/`guardrail_flag` code | MINOR | update controlled-vocabulary doc |
| Remove/rename field, narrow type, change unit | **MAJOR** | `/v2` path + deprecation window (≥30 days) + migration guide |
| DB column add (new `*_version`, new table) | Alembic migration | additive; backfilled/nullable |

## 7. Version-recording invariants (enforced by contract tests, M3+)

1. Every published `MarketStateRun` carries `schema_version`.
2. Every `runs` row has a non-null value for **every** `*_version` column it applies to (degraded runs still
   record provider attempts via Call Records; if zero providers succeeded, `provider_version`/`model_version`
   record the *last attempted* provider/model with the degraded flag).
3. Replaying a run pins **all** artifact versions from its `runs` row; a replay that can't resolve a version
   fails loudly (never silently uses "latest").
4. Any schema/DTO/config/rule change updates its version **and** the traceability/changelog in the **same**
   milestone (§8 divergence-is-a-defect).

## 8. What this enables

- **Reproducibility:** any run is re-runnable under its exact artifact set, years later (ADR-004/007).
- **Safe evolution:** the open/closed enum design + reserved slots keep the roadmap's additions MINOR
  (ADR-013), so consumers rarely face a MAJOR.
- **Auditability:** a reviewer can point at a run and know precisely which rules, weights, prompts, provider,
  model, and code produced it.
