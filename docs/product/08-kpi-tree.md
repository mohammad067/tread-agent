# Success Metrics & KPI Tree

> **Milestone 0 deliverable.** **Product KPIs** (does the product deliver its promise?) kept **distinct** from
> **model-quality metrics** (is the engine's judgment any good?), with documented linkage. Confusing the two
> is a category error: a product can be perfectly fresh and available while its regime calls are no better
> than a coin flip — and vice versa.
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

---

## 0. The two families (why they're separate)

| Family | Question it answers | Owner | Where measured |
|--------|--------------------|-------|----------------|
| **Product KPIs** | Is the product delivered, fresh, stable, adopted? | PM / Ops | Ops metrics, API telemetry |
| **Model-quality metrics** | Is the Market State *correct/useful* vs. reality & baselines? | Evaluator (P3) | Evaluation pipeline (F-10) |

A green product KPI dashboard with red model-quality metrics means "we ship garbage reliably." Both families
must be read together — but never averaged into a single vanity number.

---

## 1. Product KPI tree

```
North-Star (Product): Trustworthy, timely Market State that consumers rely on
│
├── Freshness
│   ├── KPI-P1  Scheduled-run freshness SLA: run published ≤ 10 min after 6h tick   (target ≥ 99%)
│   ├── KPI-P2  Event-run latency: published ≤ 5 min from trigger                    (target p95 ≤ 5 min)
│   └── KPI-P3  Missed-run rate: no run within 6h+15min                              (target ≈ 0)
│
├── Reliability / Availability
│   ├── KPI-P4  API availability                                                     (target ≥ 99.5%)
│   ├── KPI-P5  API latency p95 (/v1/state/latest)                                   (target ≤ 300 ms)
│   └── KPI-P6  Degraded-run rate (data-gap or LLM-fallback)                         (track; alert on spike)
│
├── Contract Stability (serves P2)
│   ├── KPI-P7  Breaking schema changes per quarter                                  (target 0 unplanned)
│   ├── KPI-P8  Schema-validation pass rate of published runs                        (target 100%)
│   └── KPI-P9  Deprecation-notice lead time honored                                 (target 100% per policy)
│
├── Explainability Integrity (serves P1/P4)
│   ├── KPI-P10 % runs where every causal_link resolves to an activated rule         (target 100%)
│   ├── KPI-P11 % activated rules with economic_rationale + trader sign-off          (target 100% — hard gate)
│   └── KPI-P12 Guardrail-flag rate (contradiction/consistency)                      (track; investigate trend)
│
├── Cost Governance
│   ├── KPI-P13 External LLM Provider cost per run (trend)                           (track; budget-aware)
│   └── KPI-P14 Monthly External LLM Provider spend vs. configured budget            (alert at 80%)
│
└── Adoption (serves P2)
    ├── KPI-P15 Active integrations / API consumers                                  (track)
    └── KPI-P16 Endpoint usage distribution (latest vs. history vs. evaluation)      (track)
```

## 2. Model-quality metric tree (owned by P3, produced by F-10)

```
North-Star (Model): Market State beats naive baselines, honestly calibrated
│
├── Directional Accuracy (per asset, per trigger_type)
│   ├── KPI-M1  Accuracy vs. persistence baseline (lift > 0)
│   └── KPI-M2  Accuracy vs. always-neutral baseline (lift > 0)
│
├── Probabilistic Quality
│   ├── KPI-M3  Brier score (per asset, per trigger_type; lower better)
│   └── KPI-M4  Calibration error across confidence buckets (0.5–0.6 … 0.9–1.0)
│
├── Component Value (ablation A–D, F-9/F-10)
│   ├── KPI-M5  Lift of B over A (deterministic news adds value)
│   ├── KPI-M6  Lift of C over B (LLM sentiment adds value)
│   └── KPI-M7  Lift of D over C/B (synthesis adds value)  ← pre-registered decision rule attaches here
│
├── Divergence / Novelty
│   ├── KPI-M8  % runs where External LLM Provider output differed from rule-engine-only
│   └── KPI-M9  Novelty-flag rate → rule-authoring backlog signal
│
└── Outcome hygiene
    └── KPI-M10 % runs with outcomes recorded at +6h/+24h (coverage of the eval set)
```

## 3. Documented linkage (how the families connect)

The families are separate but not independent. Explicit linkages:

| Product KPI | Links to model metric | Nature of link |
|-------------|-----------------------|----------------|
| KPI-P6 Degraded-run rate | KPI-M7 synthesis lift | More fallback runs → less LLM contribution measurable → weakens the ablation signal. |
| KPI-P11 rationale/sign-off | KPI-M1/M2 accuracy | Trader-reviewed rules are the hypothesis; accuracy tests whether the hypothesis holds. |
| KPI-P12 guardrail-flag rate | KPI-M8 divergence | High divergence with high flags may indicate the External LLM Provider is fighting the rules — investigate. |
| KPI-P13/14 cost | KPI-M7 synthesis lift | The pre-registered rule weighs synthesis **value** (M7) against its **cost** (P13). If D doesn't beat B by X Brier, the costly role is removed. |
| KPI-P1/P2 freshness | KPI-M3 Brier by trigger_type | Event-run value depends on being fast *and* right; freshness without accuracy is theater. |

## 4. Targets, tracking, and honesty rules

- **MVP targets are directional, not contractual** for model-quality metrics — we don't yet know the true
  achievable Brier. The MVP's job is to **measure** M1–M10 credibly, separated by `trigger_type`, so targets
  can be set from real baselines by Milestone 6.
- **No single composite score.** We never collapse P-family and M-family into one number; each is reported in
  its own panel.
- **Baselines are first-class.** Any accuracy claim (M1/M2) is meaningless without its baseline shown
  alongside — persistence and always-neutral are reported every time.
- **Confidence is not accuracy.** KPI-M4 (calibration) checks whether stated system confidence matches
  realized hit-rate; a well-calibrated low-confidence engine is honest, a miscalibrated high-confidence one is
  dangerous.

## 5. Where each KPI is produced (forward reference)

| KPI group | Produced by | Milestone it goes live |
|-----------|-------------|------------------------|
| P1–P3 freshness | Scheduler/pipeline metrics | M5 |
| P4–P6 reliability | API + observability | M5 |
| P7–P9 contract | CI contract tests + release policy | M2/M3 |
| P10–P12 explainability integrity | Guardrails + rule validation | M3 |
| P13–P14 cost | Per-run cost logging | M4/M6 |
| P15–P16 adoption | API telemetry | M5+ |
| M1–M10 model quality | Evaluation & Replay (F-9/F-10) | M6 |

> **Milestone 0 commitment:** the product will be built so that **every KPI above is measurable** — the
> Event Log, versioning, and `trigger_type` separation exist precisely so M-family metrics are computable and
> P-family SLAs are observable. A KPI we cannot instrument is a design gap, surfaced now rather than at M6.
