# ADR-005: Regime-first analysis with USD/IRR low-sensitivity exception

- **Status:** Accepted (2026-07-19)
- **Deciders:** Senior Trader, AI Systems Architect
- **Related:** ADR-001; challenges A2 (deterministic regime confidence), A6 (F&G not in regime), A7 (USD/IRR
  external drivers)

## Context
Assets do not move in a vacuum; the market-wide **Regime** (risk_on / risk_off / transition / event_driven)
conditions how each asset is read. But **USD/IRR** (Tehran parallel-market proxy) is driven mostly by domestic
factors and is largely insensitive to global risk-on/off.

## Decision
Compute the **Global Regime first**, then analyze each asset in the regime's context. **Exception: USD/IRR** has
`regime_sensitivity: low` and is analyzed on **domestic drivers** (its own rules; DXY / local gold-coin premium
if available — A7/O2; stale-price handling for Tehran hours). Regime is **mostly deterministic**;
`regime.confidence` is a **deterministic** scalar (concordance + distance-to-boundary — A2), never LLM-set.
The Global Regime uses **macro** inputs (surprises, risk_score, cross-asset), **not** crypto Fear & Greed
(A6).

## Alternatives Considered
- **Per-asset analysis with no global regime**: rejected — loses the shared backdrop that makes cross-asset
  reads coherent.
- **Apply the regime uniformly to all assets** (incl. USD/IRR): rejected — a desk would laugh; USD/IRR ignores
  most global risk swings. Hence the explicit exception.
- **LLM-classified regime**: rejected — unauditable, unreplayable; regime must be deterministic.

## Consequences
- (+) Coherent cross-asset context; realistic USD/IRR handling; deterministic, replayable regime + confidence.
- (−) A two-phase rule evaluation is needed for regime-guarded rules (matched after regime is known) — see
  [pipelines.md §2](../architecture/pipelines.md); flagged as OQ for exact split.
