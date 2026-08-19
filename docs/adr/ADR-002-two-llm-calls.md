# ADR-002: Two separate LLM calls (sentiment vs. synthesis)

- **Status:** Accepted (2026-07-19)
- **Deciders:** AI Systems Architect, Senior Trader
- **Related:** ADR-001, ADR-007, ADR-011
- **Amended:** 2026-08-18 — Call #1 is conditional on fresh, relevant evidence; Call #2 remains independent.

## Context
Sentiment scoring and explanation synthesis are different jobs with different failure modes. If one call both
scores sentiment and writes the narrative, the score can bend toward a "nicer narrative" — a subtle bias that
corrupts the one number the LLM is allowed to set.

## Decision
Two **separate** LLM jobs, **never merged**:
- **Call #1 (Sentiment):** a non-empty weighted News Digest → sentiment only for assets represented in the
  digest. Runs **before** scoring. It is skipped when deterministic freshness/relevance filtering produces an
  empty digest; this normal no-evidence state produces no Call Record and is not provider degradation.
- **Call #2 (Synthesis):** full State Vector + activated rules + sentiment → human summaries, ordinal drivers,
  novelty flags, data-gap declarations. Runs **last**, including when sentiment is absent.
Sentiment output must **not** depend on synthesis output. Each call degrades independently (ADR-011 DR-5).

For a partially populated digest, Call #1 receives only asset symbols that have deterministic
`asset_weights` evidence. Assets without eligible news retain `sentiment=null`; no neutral zero is fabricated.
Absence of fresh relevant news is not itself a Data Gap and does not mark the Run degraded.

## Alternatives Considered
- **Single merged call**: rejected — couples the sentiment score to narrative generation (the bias above) and
  makes ablation of the two roles impossible.
- **Three+ calls** (split novelty out): rejected for MVP — novelty fits naturally in synthesis; more calls =
  more cost/latency without demonstrated value. Revisit via ablation.

## Consequences
- (+) Unbiased sentiment; each role independently ablatable (C vs D); independent degradation.
- (+) No provider is asked to infer sentiment without fresh evidence; synthesis remains available from the
  deterministic State Vector.
- (−) Two calls cost more than one; mitigated by self-consistency being **off by default** (ADR-007 / A3) and
  by both calls sharing the provider-agnostic Gateway.
