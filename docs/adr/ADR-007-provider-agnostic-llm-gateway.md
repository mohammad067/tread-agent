# ADR-007: Provider-Agnostic LLM Gateway (MarketReasoner port + Adapter layer)

- **Status:** Accepted (2026-07-18) — **architecture frozen** for this concern ahead of Milestone 1.
- **Deciders:** Principal Software Architect, AI Systems Architect, Senior Backend Engineer (with Trader &
  Blockchain personas consulted on non-impact to determinism).
- **Supersedes / re-scopes:** the master-prompt seed "ADR-007 — Provider-independent MarketReasoner adapter
  layer" and folds in decision **D4** (`docs/product/00-decisions-and-open-items.md §3.1`).
- **Related:** ADR-001 (deterministic core primary), ADR-002 (two LLM calls), ADR-004 (replay + immutable
  snapshots), **ADR-011 (Degraded Run & failure isolation)** — split out from this ADR.
- **Frozen invariants:** see the master list in `docs/architecture/llm-provider-architecture.md §12`.

---

## Context

The Market State Engine delegates exactly three jobs to a language model — news sentiment, novelty detection,
and explanation synthesis (ADR-001) — while **all** market numbers stay deterministic. The project **owns no
model**: language understanding is an external, third-party dependency (decision D4). Vendors differ in SDKs,
auth, request/response shapes, streaming semantics, structured-output mechanisms, rate limits, token
accounting, and failure modes — and the vendor landscape changes constantly (OpenAI, Anthropic Claude, Google
Gemini, Grok, DeepSeek, Mistral today; local/self-hosted, Azure OpenAI, OpenRouter, AWS Bedrock, Google Vertex
tomorrow).

Two forces must be reconciled:

1. **Provider independence (hard requirement).** The Core must know nothing about any vendor. Swapping or
   adding a provider must not touch business logic, rules, pipeline, prompts, or replay.
2. **Replay integrity (ADR-004).** Every LLM call must be reproducible years later — which means the exact
   provider, model, prompt, and response must be captured, even as the underlying vendor model drifts or
   disappears.

Without a firm boundary, vendor concepts leak into the Core (a `import openai` in a scoring module; a
Claude-specific tool-call shape in a prompt), and the product loses both portability and auditability.

## Decision

Introduce a **single, provider-agnostic boundary** with a strict dependency direction. The Core depends on one
interface; everything vendor-specific lives behind it and is selected by configuration.

```
Deterministic Engine → Rule Engine → MarketReasoner (PORT) → LLMGateway → Provider Adapter → Vendor API
                                          ▲                        │
                          the ONLY LLM-facing type the             ├── routing (priority / weighted)
                          Core is allowed to reference             ├── retry / timeout policy
                                                                   ├── failover chain (→ ADR-011)
                                                                   ├── health monitor + circuit breaker
                                                                   ├── cost + metrics recording
                                                                   └── replay Call Record capture
```

### D-1 — `MarketReasoner` is the only LLM-facing type the Core may reference
- The Core imports **only** the `MarketReasoner` port: `analyze_sentiment(ReasoningRequest) → ReasoningResponse`
  and `synthesize(ReasoningRequest) → ReasoningResponse` (exact DTOs finalized in Milestone 2).
- The Core has **zero** compile-time or runtime knowledge of any vendor. No vendor SDK is importable from
  `core/`, `features/`, `rules/`, `scoring/`, `pipeline/`, `guardrails/`, or `evaluation/`. (Enforced as an
  import-boundary lint check in CI from Milestone 3.)

### D-2 — `LLMGateway` implements the port; Provider Adapters implement vendors
- `LLMGateway` is the sole implementation of `MarketReasoner` used in production. It owns routing, resilience,
  observability, and replay capture — **not** business logic.
- Each vendor is a **Provider Adapter** (`OpenAIProvider`, `ClaudeProvider`, `GeminiProvider`, …) implementing
  a narrow internal `ProviderAdapter` interface: `complete(RenderedPrompt, CallParams) → RawProviderResult`.
- **Adding a provider = one new adapter + one config entry.** No changes to business logic, rules, pipeline,
  prompts, or replay. (This is a testable invariant, not an aspiration — see Consequences.)

### D-3 — Providers are configuration, never code
- All provider settings live in `config/models/providers.yaml` (versioned; recorded per Run). Fields per
  provider: `enabled`, `priority`, `weight`, `timeout`, `retries`, `models`, `temperature`, `max_tokens`,
  plus circuit-breaker thresholds. **No provider values appear in code** — no hardcoded model ids, endpoints,
  or vendor names in `src/`.
- Changing provider/model/temperature/timeout/routing is a **config change with zero code diff**. Secrets
  (API keys) come from environment variables only (12-factor), never from the config file.

### D-4 — Prompts belong to the application, not the provider
- Prompt templates live in `prompts/` (versioned, hashed — ADR per §11 seed). The application renders a
  **provider-neutral `RenderedPrompt`**; the adapter only transports it. The rendered prompt text is
  **identical regardless of vendor**; adapters may wrap it in vendor envelope/format but must not alter its
  semantic content.
- Structured-output enforcement is expressed once in application terms; each adapter maps it to that vendor's
  mechanism (JSON mode, tool/function calling, response schema) — a translation, not a re-authoring.

### D-5 — Multi-provider strategy is declarative
The Gateway supports, all driven by `providers.yaml` with **no application-code changes**:
- **Provider priority** — ordered failover preference.
- **Weighted routing** — distribute calls across providers by weight (e.g., cost/latency balancing, A/B).
- **Retry policy** — per-provider attempts, backoff.
- **Timeout policy** — per-provider deadlines.
- **Provider health monitoring** — rolling success/latency/timeout tracking.
- **Circuit breaker** — trip a provider out of rotation on sustained failure; half-open probe to recover.
- **Temporary provider disabling** — `enabled: false` removes a provider without deleting its config/history.

### D-6 — Every call is captured for replay, cost, and metrics
The Gateway records, for **every** attempt, a **Call Record** into the Event Log (ADR-004):
`provider`, `model_id`, `prompt_version`, `prompt_hash`, `response_hash`, full `response`, `latency_ms`,
`input_tokens`, `output_tokens`, `estimated_cost`, `retries`, `finish_reason`, `attempt_index`,
`outcome` (success / timeout / error / circuit_open). This makes replay reproducible years later and makes
cost governance and provider metrics **automatic** (no manual accounting).

### D-7 — Metrics are operational only
Provider metrics (success/timeout/failure rate, avg latency/tokens/cost, fallback frequency) are exported for
operations. They **never** feed back into market scores, regime, rules, or any deterministic output. This is a
hard wall: an unhealthy provider changes *routing*, never *market truth*.

### D-8 — Failure isolation → Degraded Run (delegated to ADR-011)
A provider failure never crashes the pipeline. The full failover chain and the deterministic-only Degraded Run
policy are specified in **ADR-011** to keep this ADR focused on the abstraction.

### D-9 — Testing seams are first-class
The `ProviderAdapter` interface admits test doubles that require **no internet**: `FakeProvider` (canned),
`MockProvider` (assertable), `DeterministicProvider` (fixed function of input, for reproducible unit tests),
`ReplayProvider` (serves recorded Call Records from the Event Log). CI always uses these; a live vendor is
never called in tests or replay.

## Alternatives Considered

1. **Direct vendor SDK in the pipeline (no abstraction).** Simplest to start. **Rejected:** vendor concepts
   leak into the Core; swapping providers becomes a cross-cutting rewrite; replay breaks when the SDK changes;
   violates the hard provider-independence requirement.
2. **A single generic HTTP client configured per vendor (no adapters).** Config-only, no per-vendor code.
   **Rejected:** vendors differ in auth, structured-output, token accounting, and error semantics too much for
   one client; correctness (structured output, cost capture) would degrade to lowest-common-denominator.
3. **Third-party multi-provider router library as the boundary (e.g., a gateway SaaS/lib as the Core's
   dependency).** Fast to adopt. **Rejected as the *boundary*:** it becomes a new vendor lock-in at the
   abstraction seam and may not capture our exact Call Record for replay. **However** — such a library/service
   is perfectly acceptable *behind* our `ProviderAdapter` interface (e.g., an `OpenRouterProvider`), because
   the Core still sees only `MarketReasoner`. The boundary stays ours.
4. **Let each prompt be authored per provider.** Maximizes per-vendor quality. **Rejected:** multiplies prompt
   maintenance by the provider count, breaks prompt-hash replay equivalence across providers, and couples
   prompts to vendors (violates D-4).

## Consequences

**Positive**
- **True provider independence.** The Core is portable across every current and future vendor; swaps are
  config changes.
- **Lossless, long-lived replay.** The Call Record captures exactly what was sent and received.
- **Automatic cost governance & metrics.** Nothing is hand-accounted; budgets and dashboards read from Call
  Records.
- **Resilience without code churn.** Priority, weighting, failover, retries, timeouts, health, and circuit
  breaking are all declarative.
- **Testable offline.** Deterministic/replay providers make CI hermetic (no internet).
- **Future-proof.** Local/self-hosted, Azure OpenAI, OpenRouter, Bedrock, Vertex all slot in as adapters.

**Negative / costs (accepted)**
- **Upfront abstraction cost.** Building the Gateway + adapters + Call Record is more work than a direct SDK
  call — justified by portability, replay, and governance being core value props.
- **Lowest-common-denominator risk.** The neutral interface may not expose a vendor's most exotic feature.
  Accepted: the three LLM jobs need mainstream capabilities (chat + structured output); exotic features can be
  added to the interface deliberately if ablation shows value.
- **Adapter maintenance.** Each vendor's API drift requires adapter upkeep — but isolated to that adapter,
  never the Core.

**Enforcement (from Milestone 3 CI)**
- Import-boundary check: no vendor SDK importable outside `reasoning/adapters/`.
- Contract test: adding a `NullProvider` adapter + one config entry wires end-to-end with **zero** diffs
  outside `reasoning/adapters/` and `config/`.
- Replay regression: a recorded Call Record reproduces byte-identically via `ReplayProvider`.

## Frozen scope

This ADR is **Accepted and frozen** for the provider-abstraction boundary. Changes require a superseding ADR.
The broader Milestone 1 architecture (full component diagram, module catalog, DB schema, sequence diagrams)
builds **on top of** this frozen boundary and must not violate its invariants.
