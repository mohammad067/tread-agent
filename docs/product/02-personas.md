# Personas & Jobs-to-be-Done

> **Milestone 0 deliverable.** Four personas, each with goals, pains, JTBD, and the **specific outputs**
> that serve them. Persona IDs (P1–P4) are referenced by the PRD, use cases, and traceability matrix.
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

---

## P1 — Dashboard Analyst ("Nika")

Reads the Timeline and asset cards to stay oriented on market conditions.

- **Context:** Watches markets through the frontend dashboard; not a coder; time-pressured, especially around
  releases. Reads Persian primarily.
- **Goals (JTBD):**
  - *When I start my session,* I want a current, trustworthy read on each asset and the overall Regime, *so I
    can* orient in under a minute without assembling raw indicators myself.
  - *When the market moves,* I want to know **what changed and why**, *so I can* explain it to others and act
    on my own judgment.
- **Pains:**
  - Raw dashboards show numbers without meaning; she reconstructs the story every time.
  - She can't tell whether a move is noise or signal.
  - Stale prices look identical to fresh ones and mislead her.
- **Outputs that serve P1:**
  - `human_summary_fa` (Persian) per asset — the plain-language read.
  - `regime.state` + `regime.changed_this_run` + `regime.drivers` — the market backdrop.
  - `scores` + `market_health_index` — the at-a-glance condition.
  - `causal_links` + `activated_rules` — the "why."
  - `is_stale` / `data_gaps` — honesty about freshness.
- **Anti-goals:** She must **never** read the state as advice. UX enforces "observation" framing.

---

## P2 — Developer Integrator ("Omid")

Consumes the JSON contract to build the dashboard or downstream tools.

- **Context:** Backend/frontend engineer; never talks to us if the docs are good; English-first.
- **Goals (JTBD):**
  - *When I integrate,* I want a **stable, versioned, fully documented JSON contract** and predictable
    endpoints, *so I can* build without reverse-engineering.
  - *When the schema evolves,* I want **explicit version signals and deprecation notices**, *so I* don't ship
    breakage.
- **Pains:**
  - Undocumented or silently-changing fields.
  - Ambiguity about which fields are always present vs. optional/nullable (e.g., `onchain_context: null`).
  - No way to know the "shape" of a degraded/stale run in advance.
- **Outputs that serve P2:**
  - `MarketStateRun` schema (frozen, versioned) + `schema_version`.
  - REST endpoints: `/v1/state/latest`, `/v1/runs/{run_id}`, `/v1/runs?...`, `/v1/evaluation/summary`,
    `/v1/health`.
  - `meta` envelope (`api_version`, `next_scheduled_run`, `disclaimer`).
  - Golden sample outputs as fixtures he can code against.
  - Release & deprecation policy ([10-release-policy.md](10-release-policy.md)).
- **Anti-goals:** He should never need to guess field semantics; the traceability matrix + dictionary are for
  him.

---

## P3 — Internal Evaluator / Quant ("Sara")

Audits calibration, ablations, and whether the External LLM Provider's roles earn their keep.

- **Context:** Quantitative analyst inside the team; rigorous; English-first; owns the "does this work?"
  question.
- **Goals (JTBD):**
  - *When I assess quality,* I want **directional accuracy vs. baselines, Brier scores, and calibration
    buckets, separated by Trigger Type**, *so I can* judge the engine scientifically.
  - *When I question a component,* I want to **replay ablation variants A–D** on identical inputs, *so I can*
    measure each part's contribution and enforce the pre-registered decision rule.
  - *When I audit a specific Run,* I want its **exact inputs, prompts (hashed), versions, and output**, *so I
    can* reproduce it precisely.
- **Pains:**
  - Metrics that mix scheduled and event runs and hide effects.
  - Non-reproducible runs (missing inputs, drifting external-provider model behavior).
  - "Confidence" numbers that pretend to be probabilities.
- **Outputs that serve P3:**
  - Event Log (immutable input snapshots + prompt hashes + all versions).
  - `/v1/evaluation/summary` + monthly evaluation report.
  - Replay Harness + ablation variants + Outcome records.
  - `confidence` documented as **system confidence**, calibration reserved (Platt scaling extension point).
- **Anti-goals:** She must not be handed unauditable numbers; everything she sees must be reproducible.

---

## P4 — Desk Trader ("Reza")

Uses the Market State as **pre-trade context** — served, never advised.

- **Context:** 15+ years, macro + crypto desks. Skeptical. Will discard anything that isn't market-realistic.
  Reads both Persian and English.
- **Goals (JTBD):**
  - *When a macro event prints,* I want a fast, realistic read of the cross-asset impact tied to a defensible
    rationale, *so I can* fold it into my own judgment.
  - *When I read a Rule's effect,* I want an **economic rationale I would sign**, *so I* trust the engine
    isn't naive.
- **Pains:**
  - Naive rules (e.g., "hot CPI → gold bearish" unconditionally) that a desk would laugh at.
  - Noise thresholds that flag ordinary volatility as signal.
  - Sentiment scores biased toward a "nicer narrative."
- **Outputs that serve P4:**
  - `activated_rules` with `economic_rationale` and `reviewed_by: senior_trader`.
  - `regime` + per-asset `scores` with regime-aware interpretation.
  - Surprise-based event effects (`trigger_detail`, `expectation_context.recent_surprises`).
  - Noise-threshold-aware Outcomes (ATR-relative — challenge A5).
- **Anti-goals:** He is **served context, never advice**. The moment output reads as a recommendation, it has
  failed him and compliance.

> **P4 is also our internal reviewer persona.** Per the master prompt, the Senior Trader signs off every Rule
> and reviews every sample output for market realism. An output this persona would laugh at is a defect.

---

## Persona → primary output map (quick reference)

| Output | P1 Analyst | P2 Developer | P3 Evaluator | P4 Trader |
|--------|:---------:|:------------:|:------------:|:---------:|
| `human_summary_fa` | ●●● | ○ | ○ | ●● |
| `regime.*` | ●●● | ● | ●● | ●●● |
| `scores` + `market_health_index` | ●●● | ● | ●● | ●●● |
| `activated_rules` + `economic_rationale` | ●● | ● | ●● | ●●● |
| `causal_links` | ●●● | ● | ● | ●● |
| `is_stale` / `data_gaps` | ●●● | ●● | ●● | ●● |
| JSON schema + endpoints + `meta` | ○ | ●●● | ●● | ○ |
| Event Log + Replay + Ablations | — | ● | ●●● | ● |
| `/v1/evaluation/summary` + monthly report | ○ | ● | ●●● | ●● |
| `confidence` (system confidence) | ●● | ● | ●●● | ●● |

●●● primary · ●● important · ● incidental · ○ minimal · — none

> Every row maps to at least one persona need; every persona has at least one ●●● output. Fields serving
> **no** persona are flagged for removal in [05-traceability-matrix.md](05-traceability-matrix.md).
