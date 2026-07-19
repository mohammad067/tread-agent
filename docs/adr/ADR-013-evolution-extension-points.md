# ADR-013: Reserved extension points for the Evolution Roadmap

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, AI Systems Architect, Senior Blockchain Engineer
- **Related:** master-prompt §5 (Evolution Roadmap), ADR-007; Milestone 0 schema (§11.1)

## Context
The MVP is Phase 1 of a seven-phase roadmap. The master prompt requires that **no future phase force a
ground-up redesign**: each phase must be absorbed by a **named extension point** that exists today, with
current components surviving unchanged. We must fix those extension points in the architecture now, even though
they carry **zero implementation** in the MVP.

## Decision
Reserve the following extension points as **schema slots / interfaces now, zero implementation now**:

| Extension point | Absorbs (phase) | Reserved as |
|-----------------|-----------------|-------------|
| `expectation_context` | Phase 4 Expectation Layer | schema slot, fed by event surprises in MVP |
| `onchain_context` | Phase 3 On-chain Context | schema slot, `null` in MVP (Blockchain persona owns) |
| Confidence calibration hook | calibration (Platt scaling) | a deterministic post-processing seam on `confidence` |
| Rule store interface | Phase 2 Dynamic Rules (DB, hot-reload) | RuleEngine reads via a loader interface; YAML today, SQL past ~50 rules (ADR-003) |
| `MarketReasoner` port | Phase 3+ deeper NLU, new providers | frozen provider boundary (ADR-007) |
| Source port interface | new assets/sources | one new ingestor per source; new asset = one config file |
| Recommendation layer boundary | Phase 6 (a layer **above** Market State) | consumes the JSON contract; never inside the engine |

**Rule:** every phase in the roadmap must name which reserved point absorbs it and which current components stay
unchanged. A phase that would require redesigning a frozen boundary is a **red flag** requiring a superseding
ADR, not a silent change.

## Alternatives Considered
- **Build extension points fully now**: rejected — speculative generality; violates "no over-engineering"
  (§7). Reserve the seam, not the implementation.
- **Add extension points when needed**: rejected — retrofitting a slot into a frozen schema is a breaking
  change; reserving `null`/documented slots now keeps future additions **MINOR** (release policy).

## Consequences
- (+) Future phases slot in additively; the schema and ports absorb them without a rewrite.
- (−) A few always-`null`/surprise-only fields exist in the MVP contract — accepted; they are documented in the
  traceability matrix as reserved, not gaps.
