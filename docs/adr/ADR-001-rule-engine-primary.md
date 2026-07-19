# ADR-001: Deterministic Rule Engine as primary path, LLM as exception layer

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, AI Systems Architect, Senior Trader (rationale gate)
- **Related:** ADR-002 (two calls), ADR-003 (YAML rules), ADR-004 (replay), ADR-007 (provider-agnostic LLM),
  ADR-011 (degraded run)

## Context
Market interpretation could be **LLM-centric** (flexible, opaque, hard to replay) or **rule-centric** (rigid,
auditable, testable). The product's core value props are **explainability, auditability, and scientific
evaluability**. An LLM-centric design that computes numbers cannot be replayed across model versions and cannot
be audited field-by-field.

## Decision
**Rules + deterministic scoring produce all numbers.** The External LLM Provider has exactly three jobs:
(1) score news sentiment, (2) flag novelty outside the rule set, (3) synthesize explanations. Each job must
earn its keep via ablation (A–D). The LLM performs **no arithmetic** and sets **no** market number
(trend/risk/MHI/regime/confidence).

## Alternatives Considered
- **LLM-centric pipeline** (LLM produces scores/regime): rejected — numbers become unauditable and replay loses
  meaning across model versions.
- **Hybrid with LLM-adjustable scores**: rejected — the moment the LLM can nudge a number, honest weights and
  replay both break.

## Consequences
- (+) Replayable, testable, explainable; the causal graph is assembled only from rule edges.
- (−) Rules lag genuinely novel market dynamics; mitigated by **novelty flags** feeding the rule-authoring
  backlog, and by ablation deciding whether each LLM role is worth keeping.
- Structurally enforced by the Clean-Architecture dependency rule (Core reaches the LLM only via
  `MarketReasoner`; no math in the LLM path).
