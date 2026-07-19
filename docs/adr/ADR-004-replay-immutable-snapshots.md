# ADR-004: Replay Harness + immutable input snapshots as a day-one requirement

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, AI Systems Architect, Evaluator persona
- **Related:** ADR-001, ADR-006 (storage), ADR-007 (Call Records), ADR-011

## Context
Scientific evaluability is a core value prop: every run must be reproducible and any pipeline variant must be
runnable over history for paired comparison. This is impossible if inputs, prompts, or provider responses are
lost, or if any stage is non-deterministic in a way we don't capture.

## Decision
**Replay is a day-one requirement, not a later feature.** Every run **immutably** stores: raw input snapshots
(+hash), rendered prompts (+hash), **Call Records** (provider/model/response/tokens/cost/latency), full output,
and **all versions**. The Event Log is **append-only** and in every backup. The deterministic core replays
**byte-identically** on identical inputs+versions; LLM calls replay via `ReplayProvider` from Call Records
(no network). A design choice that makes offline replay impossible or lossy is **wrong** (§7).

## Alternatives Considered
- **Add replay later**: rejected — retrofitting immutability/capture after the fact loses the early history and
  invites non-deterministic shortcuts that can't be undone.
- **Store only outputs**: rejected — cannot reproduce or ablate without the exact inputs and calls.

## Consequences
- (+) Reproducible years later even if a vendor model disappears; ablation A–D; nightly replay regression.
- (−) Storage cost + write discipline (append-only, no mutation); accepted as the price of the product's
  scientific backbone. Losing the Event Log destroys the product (§12).
