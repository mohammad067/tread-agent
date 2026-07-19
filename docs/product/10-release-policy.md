# Release & Communication Policy

> **Milestone 0 deliverable.** Changelog conventions, schema-version announcements to contract consumers, and
> deprecation rules. This protects **P2 (Developer Integrator)** from silent breakage and makes the contract
> trustworthy.
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

---

## 1. Versioning scheme

Independently versioned artifacts, each recorded in every Run's `versions` block (F-9):

| Artifact | Scheme | Bumped when | Recorded as |
|----------|--------|-------------|-------------|
| **JSON Schema** (`MarketStateRun`) | SemVer `MAJOR.MINOR.PATCH` | any field/shape change | `schema_version` |
| **Rulebook** | SemVer | any rule add/change/retire | `versions.rulebook` |
| **MHI weights** | SemVer | weight config change | `versions.mhi_weights` |
| **Prompts** | `vN#hash` | template edit (hash changes) | `versions.prompt_*` |
| **Pipeline** (code) | SemVer via git tag | release | `versions.pipeline` |
| **Provider** (External LLM) | vendor id string | provider swap in config | `versions.provider` |
| **Model** | provider model id string | model swap in config | `versions.model` |

> **Provider/model swaps are configuration events, not code releases (decision D4).** Changing `provider` or
> `model` in `config/models/providers.yaml` needs no code change and no schema bump; it is recorded per Run in
> `versions.provider` / `versions.model` and noted in the changelog `Changed` section so replay stays
> reproducible. A provider swap that changes score meaning is flagged by the nightly replay regression (§6).

**Schema SemVer semantics (the consumer-facing contract):**
- **MAJOR** — breaking: field removed, renamed, type narrowed, enum value removed, required-ness added.
- **MINOR** — additive/backward-compatible: new optional field, new enum value in an open enum, new nested
  optional object (e.g., populating a reserved slot).
- **PATCH** — non-structural: description/doc corrections, constraint relaxations that don't break consumers.

## 2. The frozen contract rule (MVP)

- `market_state_run.v1.0.0.json` is a **frozen contract** for the MVP. Changes are proposed **only** via an
  explicit **schema-change section** with rationale (master prompt §2.8) and become an ADR.
- The golden sample fixtures (§11, delivered M2) are **normative**: any change that breaks them is a **contract
  change** requiring review, a version bump, and a changelog entry.
- **O1, D1, D2 were resolved before the v1.0.0 freeze ([ADR-014](../adr/ADR-014-summary-language-units-proxy-label.md)):**
  summary is **Persian-only** (`human_summary_fa`, no EN field), USD/IRR is **IRT (Toman)**, and the USDT
  proxy is **internal-only** (no `proxy_note` field). Adding `human_summary_en` **later** would be a **MINOR**
  additive bump; changing `currency` semantics or serving Rial would be **MAJOR**. Resolving pre-freeze avoided
  an early MAJOR.

## 3. Changelog conventions

- **Format:** [Keep a Changelog](https://keepachangelog.com) style in `CHANGELOG.md`, SemVer-tagged.
- **Sections:** `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- **Every entry links a milestone deliverable** (§12 Git discipline) and, for schema/rule changes, the ADR.
- **Rules changes** additionally require the `economic_rationale` diff in the PR description (§12); the
  changelog entry references the rule id and trader sign-off.
- **Conventional Commits** feed the changelog (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`).

**Example changelog entry (illustrative — a hypothetical future EN addition):**
```
## [1.1.0] — 2026-08-15
### Added
- schema: `human_summary_en` (optional) — additive English summary, backward-compatible MINOR. [ADR-###]
### Changed
- rulebook 1.4.0→1.5.0: `cpi_hot_gold` now regime-guarded (A4). Trader sign-off: senior_trader 2026-08-14.
```
> Note: `human_summary_en` is **not** in v1.0.0 (ADR-014); the entry above illustrates how it *would* be added
> later as a MINOR change if a need arises.

## 4. Schema-version announcements to consumers (serves P2)

| Change class | Notice channel | Lead time before effect | Consumer action |
|--------------|----------------|-------------------------|-----------------|
| PATCH | Changelog entry | none required | none |
| MINOR (additive) | Changelog + release note | ship with release | optional adoption |
| MAJOR (breaking) | Changelog + **direct release note to integrators** + deprecation window | **≥ 1 release cycle (min 30 days)** | migrate before old version retires |

- Breaking changes are **never** shipped silently. A MAJOR bump publishes: what changed, why (ADR link),
  migration guidance, and the retirement date of the prior version.
- The API is versioned in the path (`/v1/…`). A breaking schema change that warrants it introduces `/v2/…`
  and runs **both** for the deprecation window.

## 5. Deprecation rules

- **Announce → grace → remove.** A field or endpoint is first marked **deprecated** (documented, still
  served), kept for the deprecation window, then removed in a MAJOR release.
- **Deprecation window:** minimum **one release cycle / 30 days**, whichever is longer, for external
  consumers.
- **Reserved slots** (`expectation_context`, `onchain_context`) are **not** deprecations when populated —
  filling a reserved, documented `null` slot is a MINOR, backward-compatible change by design.
- Deprecated items appear in the changelog `Deprecated` section with their removal target version/date.

## 6. Release process (SemVer git tags → image → changelog)

Per §12 (live from M3 for CI, full release flow from M5/M7):
1. PR merged (trunk-based, short-lived branch, Conventional Commits, links a milestone deliverable).
2. CI green (lint, mypy --strict, unit, contract, golden, schema validation, coverage gate).
3. For schema/rule changes: ADR merged + trader sign-off (rules) attached.
4. Tag `vX.Y.Z` → build Docker image → append `CHANGELOG.md` → publish release note.
5. Nightly replay regression: any diff vs. the previous pipeline version on identical inputs **fails the
   build** unless a changelog/ADR entry explains it (§12).

## 7. Communication artifacts

| Artifact | Audience | When |
|----------|----------|------|
| `CHANGELOG.md` | all | every release |
| Release note | P2 integrators | MINOR/MAJOR |
| Migration guide | P2 integrators | MAJOR only |
| Schema-freeze announcement | P2, P3 | at v1.0.0 freeze (M2) |
| Monthly evaluation report | P3, P4 | monthly (F-10) |
| ADR log updates | all engineers | per accepted decision |

## 8. Milestone 0 commitments this policy makes

- The contract will **never** break P2 silently — versioning + announcements + deprecation windows are
  mandatory, not best-effort.
- Pre-freeze resolution of O1/D1/D2 is a **release-gating** obligation on Milestone 2.
- Every artifact that can change independently is **independently versioned and recorded per Run**, so any
  consumer or evaluator can pin exactly what produced a given Market State.
