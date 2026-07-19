# LLM Provider Architecture — Frozen Specification

> **Status: FROZEN (2026-07-18), pre-Milestone 1.** This document freezes the provider-independence
> architecture so Milestone 1 designs the full system *on top of* it. It is governed by **ADR-007**
> (provider-agnostic Gateway) and **ADR-011** (degraded run / failure isolation). Terms are binding per
> [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md).
> **No code in this document.** Concrete DTO/JSON schemas are finalized in Milestone 2; shapes here are
> normative sketches, not final field lists.
> **Scope:** only the LLM-provider boundary. The complete component catalog, DB schema, and end-to-end
> sequence diagrams are Milestone 1 deliverables that must honor the invariants in §12.

---

## 1. The boundary (one picture)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              DETERMINISTIC CORE                                 │
│  Ingestion · FeatureEngine · RuleEngine · ScoringEngine · RegimeClassifier ·   │
│  Guardrails · Persistence · Evaluation · Pipeline orchestrator                 │
│                                                                                │
│   depends on  ───────────►  MarketReasoner  (PORT — the ONLY LLM-facing type)  │
└─────────────────────────────────────┬──────────────────────────────────────────┘
                                       │  ReasoningRequest → ReasoningResponse
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                 LLM GATEWAY                                     │
│  (implements MarketReasoner; owns orchestration, NOT business logic)           │
│                                                                                │
│  PromptBuilder(render) → RenderedPrompt (provider-neutral, identical per vendor)│
│  Router (priority / weighted)  →  Retry+Timeout  →  Failover chain (ADR-011)    │
│  ProviderHealthMonitor  ·  CircuitBreaker  ·  ProviderRegistry(from config)     │
│  CallRecorder → Event Log (provider, model, hashes, tokens, cost, latency…)     │
└───────────┬───────────────┬───────────────┬───────────────┬────────────────────┘
            ▼               ▼               ▼               ▼
      ProviderAdapter  ProviderAdapter  ProviderAdapter  …  (one per vendor)
       (OpenAI)         (Claude)         (Gemini)
            │               │               │
            ▼               ▼               ▼
        Vendor API      Vendor API      Vendor API        (secrets from ENV only)
```

**Dependency rule (frozen):** arrows point *down and inward*. The Core points at `MarketReasoner` and nothing
below it. Nothing below `MarketReasoner` points back up into the Core. The deterministic engine never knows
who generated the text.

## 2. Components and single responsibilities

| Component | Layer | Single responsibility | Must NOT |
|-----------|-------|-----------------------|----------|
| **MarketReasoner** (port) | Core-facing | Define the two operations the Core needs: `analyze_sentiment`, `synthesize`. | Reference any vendor; contain logic. |
| **LLMGateway** | Reasoning | Route, retry, time out, fail over, monitor health, break circuits, record calls; return a `ReasoningResponse` or a degraded marker. | Compute market numbers; author prompts; know vendor specifics beyond the adapter interface. |
| **ProviderRegistry** | Reasoning | Load enabled providers + policies from `providers.yaml` at startup/reload; expose the routing set. | Hold secrets; hardcode providers. |
| **Router** | Reasoning | Pick provider order by **priority** and **weight** among healthy providers. | Persist state; touch scores. |
| **RetryPolicy / TimeoutPolicy** | Reasoning | Per-provider attempt/backoff/deadline enforcement. | Be hardcoded (config-driven). |
| **ProviderHealthMonitor** | Reasoning | Rolling success/latency/timeout stats per provider; feed the circuit breaker and metrics. | Influence market outputs (operational only — ADR-007 D-7). |
| **CircuitBreaker** | Reasoning | Trip a failing provider out of rotation; half-open probe to recover. | Abort the pipeline. |
| **PromptBuilder** | Reasoning (app-owned) | Render versioned application templates to a **provider-neutral `RenderedPrompt`**; compute prompt hash. | Contain vendor formatting; live inside an adapter. |
| **ProviderAdapter** (per vendor) | Reasoning/adapters | Translate `RenderedPrompt`+`CallParams` to/from one vendor's API; map structured-output + token accounting + errors to neutral types. | Contain business logic; alter prompt semantics. |
| **CallRecorder** | Reasoning → Persistence | Write a **Call Record** per attempt to the Event Log for replay/cost/metrics. | Drop fields; be optional. |

## 3. Configuration design — `config/models/providers.yaml` (normative sketch)

> Secrets are **never** here. `api_key_env` names the environment variable that holds the key.
> All values below are illustrative; real values are set per environment.

```yaml
version: 1.0.0
routing:
  strategy: priority        # priority | weighted
  degrade_after_all_fail: true   # ADR-011; must remain true (frozen invariant)
defaults:
  temperature: 0
  max_tokens: 1024
  timeout_seconds: 20
  retries: 2
  backoff: {type: exponential, base_ms: 400, max_ms: 4000}
  circuit_breaker: {failure_threshold: 5, window_seconds: 120, half_open_after_seconds: 60}
providers:
  - name: openai
    enabled: true
    priority: 1
    weight: 60
    api_key_env: OPENAI_API_KEY
    models: {sentiment: gpt-5.5, synthesis: gpt-5.5}
    temperature: 0
    max_tokens: 1024
    timeout_seconds: 20
    retries: 2
  - name: anthropic
    enabled: true
    priority: 2
    weight: 40
    api_key_env: ANTHROPIC_API_KEY
    models: {sentiment: claude-sonnet-5, synthesis: claude-sonnet-5}
  - name: gemini
    enabled: false            # temporary disable — config only, no code change
    priority: 3
    weight: 0
    api_key_env: GOOGLE_API_KEY
    models: {sentiment: gemini-2.5-pro, synthesis: gemini-2.5-pro}
```

**Guarantees (frozen):**
- **Add a provider** = append one block + drop in one adapter. Nothing else changes.
- **Swap/disable/reprioritize/reweight** = edit this file. Zero code diff.
- Every field consumed here is recorded per Run so replay knows the exact routing config used.

## 4. Prompt independence (frozen)

- Templates live in `prompts/` (`sentiment/vN.md`, `synthesis/vN.md`), versioned and hashed.
- `PromptBuilder` renders a template + `ReasoningRequest` into a **`RenderedPrompt`** — provider-neutral text
  that is **byte-identical regardless of which vendor will receive it**.
- The adapter may wrap the rendered text in the vendor's envelope (roles, JSON-mode flag, tool schema) but
  **must not change its semantic content**. The `prompt_hash` is computed on the neutral rendered text, so the
  same request yields the same hash across vendors — which is what makes cross-provider replay comparisons
  valid.

## 5. Call Record — the replay/cost/metrics unit (normative sketch)

Written to the Event Log for **every attempt** (success or failure). Final schema in Milestone 2.

| Field | Purpose | Used by |
|-------|---------|---------|
| `run_id` | Correlate to the Run | replay, logs |
| `llm_job` | `sentiment` \| `synthesis` | replay, eval |
| `attempt_index` | Which attempt in the failover chain | metrics |
| `provider` | Vendor id (e.g., `openai`) | replay, cost, metrics |
| `model_id` | Exact model (e.g., `gpt-5.5`) | replay, drift audit |
| `prompt_version` | Template version (e.g., `synthesis/v1`) | replay |
| `prompt_hash` | Hash of the neutral rendered prompt | replay integrity |
| `response_hash` | Hash of the raw provider response | replay integrity |
| `response` | Full raw provider response | replay (exact reproduction) |
| `latency_ms` | Call latency | metrics, SLO |
| `input_tokens` / `output_tokens` | Token accounting | cost, metrics |
| `estimated_cost` | Computed from a versioned price table | cost governance |
| `retries` | Retry count for this attempt | metrics |
| `finish_reason` | Provider stop reason (stop/length/refusal/…) | quality, guardrails |
| `outcome` | `success` \| `timeout` \| `error` \| `circuit_open` | metrics, failover audit |

**Cost is automatic:** `estimated_cost` derives from token counts × a **versioned price table**
(`config/models/pricing.vN.yaml`), recorded per Run — no manual accounting (ADR-007 D-6). Historical cost
stays reproducible because the price table version is captured.

## 6. Provider metrics (operational only — never influence scores)

Exported from Call Records (ADR-007 D-7): per-provider **success rate, timeout rate, failure rate, avg
latency, avg token usage, avg cost, fallback frequency**, circuit-breaker state. These drive dashboards and
alerts (`LLM fallback engaged`, budget 80%, source-deviation) and **routing/health only**. A hard wall keeps
them out of every deterministic path: market scores, regime, rules, MHI, and evaluation are computed without
any reference to provider health.

## 7. Multi-provider routing (frozen behaviors)

| Behavior | Config field(s) | Semantics |
|----------|-----------------|-----------|
| Priority failover | `priority` | Try providers in ascending priority among healthy ones. |
| Weighted routing | `routing.strategy: weighted`, `weight` | First pick chosen by weight; fall through by priority on failure. |
| Retry | `retries`, `backoff` | Per-provider attempts before moving on. |
| Timeout | `timeout_seconds` | Per-provider deadline; exceeding it = failure → next provider. |
| Health monitoring | (derived) | Rolling stats gate routing eligibility. |
| Circuit breaker | `circuit_breaker.*` | Trip out on sustained failure; half-open probe to restore. |
| Temporary disable | `enabled: false` | Remove from rotation without losing config/history. |

## 8. Failure isolation & Degraded Run (per ADR-011)

```
provider fails → retry → next provider → next provider → … → ALL fail
                                                                  │
                                                                  ▼
                                        DEGRADED RUN: deterministic outputs only,
                                        LLM fields explicitly absent, flag + alert.
                                        Pipeline NEVER aborts. (ADR-011 DR-1..DR-5)
```
Partial success is preserved per LLM job (sentiment vs synthesis) — ADR-011 DR-5.

## 9. Testing seams (offline, no internet — frozen)

Behind the same `ProviderAdapter` interface:

| Double | Purpose |
|--------|---------|
| `FakeProvider` | Returns canned responses for wiring/dev. |
| `MockProvider` | Assertable calls for unit tests. |
| `DeterministicProvider` | Output = fixed pure function of input → reproducible unit tests. |
| `ReplayProvider` | Serves recorded Call Records from the Event Log → replay/regression tests. |

CI **always** uses doubles; a live vendor is never called in tests or replay (master-prompt §12).

## 10. Future-provider matrix (absorbed with zero redesign)

| Future provider | Absorbed as | Notes |
|-----------------|-------------|-------|
| Local / self-hosted LLM | `LocalProvider` adapter + config entry | Endpoint via env; no core change. |
| Azure OpenAI | `AzureOpenAIProvider` adapter | Different auth/endpoint, same interface. |
| OpenRouter | `OpenRouterProvider` adapter | A multi-vendor router *behind* our boundary (ADR-007 Alt-3). |
| AWS Bedrock | `BedrockProvider` adapter | SigV4 auth in the adapter only. |
| Google Vertex AI | `VertexProvider` adapter | GCP auth in the adapter only. |
| Any 2027+ vendor | new adapter + config entry | The boundary never moves. |

## 11. Milestone mapping (what gets built when, on this frozen boundary)

| Concern | Milestone | Note |
|---------|-----------|------|
| `MarketReasoner` port + `ReasoningRequest/Response` DTOs | M2 (contracts) | Frozen boundary → concrete schemas. |
| Call Record schema + Event Log tables | M2 | Replay fields fixed here. |
| PromptBuilder + versioned/hashed templates | M4 | Neutral `RenderedPrompt`. |
| `LLMGateway`, Router, Retry/Timeout, Health, CircuitBreaker | M4 | Config-driven. |
| First real ProviderAdapter + test doubles | M4 | Doubles land with it. |
| Degraded-run path end-to-end | M5 | Pipeline wiring. |
| Provider metrics/cost dashboards + alerts | M5/M6 | From Call Records. |
| Import-boundary CI lint | M3 | Enforces §12.1. |

## 12. Frozen invariants (changing any requires a superseding ADR)

1. **Core sees only `MarketReasoner`.** No vendor SDK importable outside `reasoning/adapters/`. (CI-enforced.)
2. **Providers are config, not code.** No vendor value (name, model, endpoint) in `src/`. Secrets via ENV only.
3. **Add-a-provider = one adapter + one config entry.** No changes to business logic, rules, pipeline,
   prompts, or replay.
4. **Prompts are application-owned and vendor-neutral.** Same rendered prompt → same `prompt_hash` across
   vendors.
5. **Every LLM attempt writes a Call Record** with provider, model, prompt version+hash, response hash,
   response, latency, tokens, cost, retries, finish_reason, outcome.
6. **Replay is lossless and long-lived** via `ReplayProvider` + Call Records; reproducible years later.
7. **Cost & metrics are automatic and operational-only**; they never influence any deterministic output.
8. **Provider failure never aborts the pipeline**; exhaustion → Degraded Run with honest absence + alert
   (ADR-011).
9. **Deterministic core, scores, rules, replay, and evaluation are unchanged** by anything below
   `MarketReasoner`. Swapping providers never changes architecture.
10. **Tests run offline** using provider doubles; no test requires the internet.

---

*Frozen by ADR-007 and ADR-011. Milestone 1 architecture builds on this and may not violate §12.*
