# ADR-002: Two separate LLM calls (sentiment vs. synthesis)

- **Status:** Accepted (2026-07-19)
- **Deciders:** AI Systems Architect, Senior Trader
- **Related:** ADR-001, ADR-007, ADR-011

## Context
Sentiment scoring and explanation synthesis are different jobs with different failure modes. If one call both
scores sentiment and writes the narrative, the score can bend toward a "nicer narrative" — a subtle bias that
corrupts the one number the LLM is allowed to set.

## Decision
Two **separate** calls per run, **never merged**:
- **Call #1 (Sentiment):** weighted News Digest → per-asset + global Sentiment Scores. Runs **before** scoring.
- **Call #2 (Synthesis):** full State Vector + activated rules + sentiment → human summaries, ordinal drivers,
  novelty flags, data-gap declarations. Runs **last**.
Sentiment output must **not** depend on synthesis output. Each call degrades independently (ADR-011 DR-5).

## Alternatives Considered
- **Single merged call**: rejected — couples the sentiment score to narrative generation (the bias above) and
  makes ablation of the two roles impossible.
- **Three+ calls** (split novelty out): rejected for MVP — novelty fits naturally in synthesis; more calls =
  more cost/latency without demonstrated value. Revisit via ablation.

## Consequences
- (+) Unbiased sentiment; each role independently ablatable (C vs D); independent degradation.
- (−) Two calls cost more than one; mitigated by self-consistency being **off by default** (ADR-007 / A3) and
  by both calls sharing the provider-agnostic Gateway.
