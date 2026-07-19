# Rule YAML Schema Contract

> **Milestone 2 — Contracts & Schemas.** The contract every rule in `rules/` must satisfy. Enforced at load by
> a **hard gate** (ADR-008): a rule missing `economic_rationale` or `reviewed_by: senior_trader` **cannot
> ship**. **Design document — no code, no rule files.** Rule matching/conflict semantics:
> [../architecture/pipelines.md §4](../architecture/pipelines.md). Terms binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> **Version:** 1.0.0

## 1. Rule object schema

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `id` | string (slug) | M | Unique across the rulebook, e.g., `cpi_hot_risk_assets_bearish`. |
| `version` | integer ≥ 1 | M | Bumped on any change to this rule. |
| `status` | enum | M | `active`\|`inactive`\|`deprecated`. Only `active` rules match. |
| `trigger` | object | M | See §2. |
| `effects` | array\<Effect\> | M (≥1) | See §3. |
| `regime_guard` | object | O | See §4 (challenge A4). |
| `half_life_hours` | number > 0 | M | Decay of this rule's influence. |
| `source` | string | M | Evidence/citation (e.g., "Fed reaction function, 2022–2025"). |
| `economic_rationale` | string (non-empty) | **M (hard gate)** | Trader-defensible market truth. |
| `reviewed_by` | const | **M (hard gate)** | Must equal `senior_trader`. |
| `reviewed_at` | date | M | Sign-off date. |

## 2. `trigger` — surprise-based conditions (not raw actuals)

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `event_type` | enum | C | `us_cpi`\|`fomc`\|`us_nfp` (event-driven rules). |
| `condition` | string (expression) | M | A **surprise-based** boolean over feature variables, e.g., `surprise_core_mom >= 0.1`. |
| `condition_vars` | array\<string\> | M | The feature variables the expression references (for validation + grounding). |

**Rule (§2 invariant):** macro-event conditions must reference a **surprise** variable
(`surprise_*`), never a raw actual — enforced by a load-time check. This encodes "rules trigger on surprise,
not actuals" (F-5) structurally.

## 3. `Effect`

| Field | Type | Req? | Notes |
|-------|------|------|-------|
| `asset` | enum (symbol) | M | Target asset, or `TOTAL_MCAP`/global. |
| `direction` | enum | M | `bullish`\|`bearish`\|`neutral`. |
| `strength` | enum | M | `dominant`\|`major`\|`moderate`\|`minor`. |
| `horizon` | string | M | e.g., `24h`. |
| `uncertain` | boolean | O | Marks a low-confidence effect (used by the gold-CPI downgrade, A4). |

## 4. `regime_guard` (challenge A4 — the gold-CPI fix, structural)

| Field | Type | Notes |
|-------|------|-------|
| `applies_in` | array\<regime state\> | The effect activates only in these regimes (e.g., `[risk_off]` or rate-cycle-tagged regimes). |
| `else` | enum | What happens outside the guard: `suppress` \| `downgrade_to_minor` \| `flag_uncertain`. |

**Design consequence:** a rule like "hot CPI → gold bearish" **must** either carry a `regime_guard` or set its
gold effect to `strength: minor` + `uncertain: true`. A load-time lint flags an unguarded, non-minor gold-CPI
effect (the "desk would laugh" check, A4/ADR-008).

## 5. Conflict handling (deterministic — OQ-3, pending Trader ruling)

When two `active` rules assign **opposing directions** to the same asset in the same run, resolution is
**deterministic** and one of (to be finalized by the Trader, OQ-3):
- (a) **highest `strength` wins** (ties → net/attenuate);
- (b) **net/attenuate** (combine magnitudes, direction of the stronger);
- (c) **flag-only** (surface both as a `guardrail_flag`, no silent pick).

This spec fixes the **contract** (conflicts are resolved deterministically and recorded); the **policy choice**
is OQ-3 and must be signed off before M3 RuleEngine implementation. Whichever is chosen, the resolution is
logged and reproducible.

## 6. Rulebook organization & versioning

- `rules/global/*.yaml` — regime + cross-asset macro rules.
- `rules/assets/{symbol}/*.yaml` — per-asset rules (incl. `usd_irr` domestic drivers).
- `rules/VERSION` — rulebook SemVer, bumped on any rule change; snapshot → `rules_versions`.
- A PR touching `rules/` must include the `economic_rationale` diff + Trader sign-off (ADR-008, §12).

## 7. Validation & testing (M3)

1. **Hard gate:** load fails if any rule lacks `economic_rationale` or `reviewed_by: senior_trader`.
2. **Surprise check:** event-rule conditions reference a `surprise_*` variable.
3. **Gold-CPI lint:** unguarded non-`minor` gold effect on a hot-CPI trigger is rejected (A4).
4. **Schema validation:** every rule validates against `schemas/internal/rule.v1.json` (contract test).
5. **Matcher unit tests:** truth tables per rule; golden fixtures for activation sets.
6. **Conflict tests:** opposing-effect scenarios resolve per the chosen OQ-3 policy, deterministically.

## 8. Example (illustrative — the §11.2 sample, corrected for A4)

The master-prompt §11.2 sample (`cpi_hot_risk_assets_bearish`) is normative **except** its unconditional
`GOLD → bearish, moderate`. Per A4/ADR-008 this MVP requires that gold effect to be **either** `regime_guard`ed
**or** downgraded to `strength: minor, uncertain: true`. The corrected rule is delivered as a golden rule
fixture in M2.
