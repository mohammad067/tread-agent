# ADR-008: Trader sign-off (`economic_rationale`) as a hard gate for rules

- **Status:** Accepted (2026-07-19)
- **Deciders:** Senior Trader, Principal Architect
- **Related:** ADR-001, ADR-003; challenge A4 (regime-guarded gold-CPI)

## Context
A rule encodes market cause→effect. A naive rule (e.g., "hot CPI → gold bearish" unconditionally) is the kind
of thing a desk would laugh at and ships wrong often. Rules must carry defensible market truth, authored/owned
by the Trader persona — not engineers guessing.

## Decision
Every rule **must** carry a non-empty `economic_rationale` and `reviewed_by: senior_trader` (with
`reviewed_at`). The **Rule Loader rejects** any rule missing either — a **hard gate** enforced at load and in
contract tests; an unreviewed rule **cannot ship**. Rules may carry **regime guards** (A4); the gold-CPI effect
must be regime-conditioned or downgraded to `minor`+`uncertain`, never unconditional `moderate`. Rule changes
require the `economic_rationale` diff in the PR (§12).

## Alternatives Considered
- **Rationale as an optional field**: rejected — optional means absent under deadline pressure; the gate must
  be hard to preserve market realism.
- **Engineer-authored rules**: rejected — violates the persona ownership boundary; engineers don't own market
  truth.

## Consequences
- (+) Every activated rule surfaces a rationale a desk would sign; trust for P4; auditable causal links.
- (−) Rule authoring is gated on Trader availability — accepted; correctness over speed for market claims.
