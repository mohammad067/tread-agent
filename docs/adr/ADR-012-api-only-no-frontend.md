# ADR-012: API-only system, no front-end

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, Product Manager (user directive: "این یک api محور هست و نباید هیچ فرانت
  اند داشته باشد")
- **Related:** master-prompt §3 (No UI implementation); Milestone 0
  [06-ux-content-requirements.md](../product/06-ux-content-requirements.md)

## Context
The user directed that the system is **API-centric with no front-end**. The master prompt already lists "No UI
implementation" as a non-goal (§3) and says we own "the contract and a mock-serving endpoint." Milestone 0,
however, wrote UX & content requirements and a persona (P1 Dashboard Analyst) that assume a UI exists somewhere.
We must reconcile these without dropping any Milestone 0 capability.

## Decision
The Market State Engine ships **only** a REST API + the `MarketStateRun` JSON contract. **No front-end** is
built: no HTML, no server-rendered views, no SPA, no `frontend/` directory. The Milestone 0
**UX & content requirements become binding obligations on API *consumers*** — communicated through the schema,
field semantics, flags (`is_stale`, `weight_type`, `is_degraded`, `guardrail_flags`), and documentation. The
engine **guarantees the data and flags** a compliant UI needs; rendering them is the consumer's responsibility.

Persona **P1 (Dashboard Analyst)** is retained as the **end-user the API serves indirectly** — their needs
shape which fields exist, but they interact through a consumer-built UI, not one we ship.

## Alternatives Considered
- **Ship a reference UI**: rejected — violates the user directive and §3; creates a second contract (UI
  expectations) that can drift from the JSON schema; dilutes focus.
- **Drop the UX requirements entirely**: rejected — the UX rules encode compliance and honesty guarantees
  (stale dimming, confidence labeling, computed-vs-ordinal) that must still be *served* by the data, even if we
  don't render them.

## Consequences
- (+) Single source of truth (the JSON contract); focus on the deterministic core + provider abstraction;
  matches §3.
- (+) UX requirements are preserved as **consumer contract obligations**, so no Milestone 0 capability is lost.
- (−) We cannot *enforce* UI-side rendering (e.g., that a consumer actually dims stale prices) — mitigated by
  shipping the flags, the golden fixtures (incl. a degraded fixture), and clear docs so a consumer can comply.
- API design ([api-design.md](../architecture/api-design.md) §10) carries the explicit consumer-obligation list.
