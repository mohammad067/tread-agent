# ADR-011: Degraded Run & Provider Failure Isolation

- **Status:** Accepted (2026-07-18) — **architecture frozen** for this concern ahead of Milestone 1.
- **Deciders:** Senior Backend Engineer, AI Systems Architect, Principal Software Architect.
- **Split from:** ADR-007 (kept there as principle D-8; specified in full here).
- **Related:** ADR-001 (deterministic core primary), ADR-004 (replay), master-prompt §4.8 guardrails,
  §12 reliability/observability.

---

## Context

The three LLM jobs (sentiment, novelty, synthesis) are delegated to an **external** provider we do not own
(D4/ADR-007). External providers fail: timeouts, rate limits, 5xx, auth expiry, content refusals, network
partitions, and outright outages. The deterministic core — indicators, scores, MHI, Rule Engine, regime,
guardrails — has **no** dependency on the provider for correctness (ADR-001).

Therefore an external provider outage must **never** be able to abort a Market State Run. A run that fails
because a vendor is down would make the product's availability hostage to a dependency that, by design, does
not affect market truth.

## Decision

### DR-1 — The failover chain
On each LLM call, the `LLMGateway` executes this chain, all governed by `providers.yaml` (ADR-007 D-5), with
**no application-code involvement**:

```
call provider[i] (highest priority / weighted pick, if healthy)
   │  success → return response, record Call Record
   │  failure → retry per that provider's retry+timeout policy
   │              exhausted → mark health event; maybe trip circuit breaker
   ▼
next healthy provider[i+1]  … repeat …
   ▼
ALL configured providers exhausted or circuit-open
   ▼
DEGRADED RUN  — deterministic outputs only, LLM fields absent, flagged + alert
```

- Circuit-open providers are **skipped** (not retried) until their half-open probe window.
- The chain order is priority; weighted routing selects the *first* pick among healthy providers, then falls
  through by priority.

### DR-2 — Degraded Run semantics
When every configured provider is exhausted/unavailable:
- The pipeline **continues**. The Rule Engine and deterministic scoring still produce a **valid, schema-
  conforming Market State** (regime, scores, MHI, activated rules, causal links).
- **LLM-generated fields are absent, not fabricated:** `scores.sentiment`, ordinal drivers, `human_summary_*`,
  and `novelty_flags` are represented as explicitly missing/degraded — never as zeros or empty strings passed
  off as real values.
- The run is marked with a **degradation flag** in `guardrail_flags[]` and an **alert** is emitted
  (`LLM fallback engaged`, §12 alerts).
- `trigger_type` and all deterministic fields are unaffected; the run is still persisted, published, and
  replayable.

### DR-3 — Never abort
There is **no** code path where an LLM/provider error aborts, blocks, or unpublishes a Run. The only outcomes
of the LLM stage are: (a) full run with LLM fields, or (b) Degraded Run without them. A provider exception
that escapes the Gateway is itself a defect caught by guardrails, which still publish-with-flags rather than
block (master-prompt §4.8 policy: publish-with-flags for this class).

### DR-4 — Determinism of the degraded path
A Degraded Run over identical inputs is **byte-identical on replay** for all deterministic fields, exactly
like a normal run — because the deterministic core is unchanged. The Degraded Run is therefore fully usable in
evaluation/ablation (it *is* ablation variant A/B territory: rules-only / +deterministic-news).

### DR-5 — Partial LLM success
If Call #1 (sentiment) succeeds but Call #2 (synthesis) fails after failover (or vice-versa), the run is
degraded **only** for the failed call's fields; the succeeded call's fields are kept. Degradation is
per-LLM-job, not all-or-nothing, so we never discard a good sentiment score because synthesis timed out.

## Alternatives Considered

1. **Fail the whole run on LLM failure.** Simplest. **Rejected:** makes availability hostage to an external
   dependency that doesn't affect market truth; violates §12 reliability SLOs and ADR-001's spirit.
2. **Retry indefinitely / block until a provider recovers.** **Rejected:** unbounded latency; a run published
   hours late is worse than a timely Degraded Run; breaks the freshness SLA.
3. **Fabricate neutral LLM outputs (sentiment = 0, empty summary) silently.** **Rejected:** dishonest — a
   fabricated 0 is indistinguishable from a real neutral read; corrupts evaluation and misleads users. Absence
   must be explicit (DR-2).
4. **All-or-nothing degradation (drop both LLM calls if either fails).** **Rejected:** wastes a successful,
   costly call and needlessly reduces output quality (DR-5).

## Consequences

**Positive**
- Provider outages degrade gracefully; the product stays available and on-SLA.
- Degraded Runs remain valid, honest, replayable, and evaluable.
- Partial-success handling preserves whatever the providers did deliver.
- Clear operator signal (flag + alert) without user deception.

**Negative / costs (accepted)**
- Consumers (P1/P2) must handle the degraded shape — mitigated by shipping a **degraded golden fixture** in
  Milestone 2 so integrators code against it up front (UC-5 AC-5.1).
- Degraded Runs carry less explanatory value (no summaries) — acceptable and, by design, visibly marked.
- Evaluation must bucket degraded runs appropriately so they don't distort synthesis-lift metrics — handled by
  the `trigger_type` + degradation-flag separation in F-10.

## Frozen scope

Accepted and frozen. The failover chain, Degraded-Run semantics, never-abort guarantee, and honest-absence
rule are invariants; changes require a superseding ADR. Threshold *values* (retry counts, timeouts, circuit
thresholds) are configuration, tunable without touching this ADR.
