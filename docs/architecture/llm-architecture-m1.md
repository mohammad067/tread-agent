# LLM Architecture (Milestone 1 context)

> **Milestone 1.** This document **does not redefine** the LLM architecture — that is **frozen** in
> [llm-provider-architecture.md](llm-provider-architecture.md) (ADR-007) and
> [../adr/ADR-011-degraded-run-failure-isolation.md](../adr/ADR-011-degraded-run-failure-isolation.md). Here we
> place the frozen boundary into the Milestone 1 system and specify the **application-side** LLM concerns that
> M1 owns: the two calls, prompt rendering, structured-output enforcement, self-consistency policy, and
> grounding. **Design only — no code, no prompt text** (prompt text is Milestone 4).
> Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> **Version:** 1.0.0

## 1. Where the LLM sits (recap of the frozen boundary)

```
Deterministic Core → Rule Engine → MarketReasoner (PORT) → LLMGateway → Provider Registry
   → Provider Router → Provider Adapter → Vendor API (OpenAI / Claude / Gemini / future)
```

The Core references **only** `MarketReasoner`. Everything below is config-driven and vendor-agnostic. Provider
selection, weighted/priority routing, retries, timeouts, health monitoring, circuit breaking, failover, Call
Records, cost logging, and provider metrics are all specified (and frozen) in the provider architecture spec.
**This M1 document owns what the *application* asks of the LLM**, not how the Gateway talks to vendors.

## 2. The two LLM calls (ADR-002) in the M1 pipeline

| | Call #1 — Sentiment | Call #2 — Synthesis |
|--|---------------------|---------------------|
| **Port method** | `MarketReasoner.analyze_sentiment` | `MarketReasoner.synthesize` |
| **Input (ReasoningRequest)** | weighted `NewsDigest` + asset list | full State Vector + activated rules + sentiment |
| **Output (ReasoningResponse)** | per-asset + global Sentiment Scores | human summaries, ordinal drivers, novelty flags, data-gap declarations |
| **Pipeline stage** | 5 (before scoring) | 7 (after scoring/regime) |
| **Degrades independently** | yes (ADR-011 DR-5) | yes |
| **Why separate** | prevents the sentiment score bending toward a "nicer narrative" (ADR-002) | synthesis may see scores; sentiment must not see synthesis |

**Sequencing rationale:** sentiment is an *input* to scoring context and must be computed before the
deterministic scores that synthesis will explain; synthesis is *last* because it narrates the finished State
Vector. Merging them would let the narrative contaminate the score — the exact failure ADR-002 prevents.

## 3. Prompt independence & rendering (frozen invariant #4, M1 detail)

- **Templates are application-owned** (`prompts/sentiment/vN.md`, `prompts/synthesis/vN.md`), versioned and
  hashed.
- **`PromptBuilder` renders** a template + `ReasoningRequest` into a **provider-neutral `RenderedPrompt`** —
  byte-identical regardless of which vendor will receive it — and computes `prompt_hash` on that neutral text.
- The **adapter** may wrap the rendered text in the vendor's envelope (roles, JSON-mode flag, tool schema) but
  **must not change its semantic content**. Same request → same `prompt_hash` across vendors → valid
  cross-provider replay comparisons.

## 4. Structured-output enforcement

- Both calls demand **structured output** validated against the internal `ReasoningResponse` schema (Pydantic
  at the boundary; JSON Schema in `schemas/internal/`).
- **Enforcement is expressed once in application terms**; each adapter maps it to that vendor's mechanism
  (JSON mode / tool-calling / response schema). If a provider returns malformed/unparseable output, it is
  treated as a **call failure** → retry → failover (ADR-011), never a fabricated result.
- **Grounding constraint (Call #2):** the response may reference **only numbers present in the request**; the
  Guardrails stage enforces this deterministically after synthesis (a violation → guardrail flag).

## 5. Self-consistency policy (challenge A3)

- **Low-temperature double-call self-consistency** for sensitive fields is a **capability**, but **config-gated
  and OFF by default** in the MVP (challenge A3), reserved for **high-surprise event runs**.
- When enabled, the Gateway issues two low-temperature calls; **divergence lowers `confidence`** (deterministic
  adjustment in scoring, not an LLM decision). Both calls are recorded as separate Call Records.
- **Why off by default:** the sentiment call runs every run; double-calling it is the single largest recurring
  cost, with marginal MVP value. The switch exists so it can be enabled where surprise magnitude justifies it.

## 6. Degraded behavior (ADR-011, M1 placement)

- If **all** providers fail for a given LLM job after retries/failover, that job's fields are **absent, not
  fabricated**: no fake sentiment, no fake summary. The run is **Degraded** (`is_degraded=true`), flagged, and
  alerted. Deterministic outputs (indicators, scores, regime, MHI, rules, evaluation) are unaffected.
- **Partial success** is preserved per job: a successful sentiment call is kept even if synthesis fails.

## 7. What the LLM may and may not do (frozen)

| May (the only three jobs) | May not |
|---------------------------|---------|
| Interpret unstructured **news** → Sentiment | Compute **any** market number (trend/risk/MHI/regime/confidence) |
| Detect **novelty** outside the rule set | Assign news weights (deterministic — F-6) |
| Synthesize **human summaries** + ordinal drivers | Invent causal edges (graph is rule-derived — §3) |
| — | Advise, predict, or recommend (compliance) |
| — | Reference numbers not in the request (grounding) |

## 8. Testing the LLM layer offline (frozen invariant #10)

- `FakeProvider` / `MockProvider` for wiring + assertions; `DeterministicProvider` for reproducible unit tests;
  `ReplayProvider` for replay/regression. **No test calls a live vendor**; CI is hermetic.
- Golden-file tests cover **PromptBuilder** output (the rendered neutral prompt) so prompt changes are visible
  and reviewed (prompt hash changes = a versioned event).

## 9. Cross-references

- Provider routing/resilience/observability/config: [llm-provider-architecture.md](llm-provider-architecture.md).
- Failure isolation & Degraded Run: [../adr/ADR-011-degraded-run-failure-isolation.md](../adr/ADR-011-degraded-run-failure-isolation.md).
- Call Record persistence: [database.md §4.5](database.md).
- Pipeline placement of the two calls: [pipelines.md §2](pipelines.md).
