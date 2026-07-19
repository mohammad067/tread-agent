# Sequence Diagrams

> **Milestone 1.** The runtime sequences for every lifecycle: scheduled run, event run, degraded run, replay
> run, outcome recording, and news ingestion. Mermaid source (renders in GitHub/most viewers). **Design only.**
> Terms binding per [../product/09-domain-dictionary.md](../product/09-domain-dictionary.md). Component roles:
> [module-catalog.md](module-catalog.md); stage detail: [pipelines.md](pipelines.md).
> **Version:** 1.0.0

---

## 1. Scheduled run (6h cron) — the happy path

```mermaid
sequenceDiagram
  autonumber
  participant CRON as Cron (6h)
  participant SCH as Scheduler
  participant ORC as Orchestrator
  participant ING as Ingestors
  participant EL as Event Log
  participant FE as FeatureEngine
  participant RE as RuleEngine
  participant NW as NewsWeigher
  participant MR as MarketReasoner (port)
  participant GW as LLMGateway
  participant SC as ScoringEngine/Regime
  participant GR as Guardrails
  participant DB as Persistence

  CRON->>SCH: tick
  SCH->>ORC: start run (run_id, run_sequence, trigger_type=scheduled)
  ORC->>ING: ingest all sources
  ING-->>EL: immutable raw snapshots (+hash, is_stale, deviation_flags)
  ORC->>FE: compute features (indicators, changes, ATR%, surprise, decay)
  ORC->>RE: match rules (surprise-based; non-guarded)
  RE-->>ORC: activations + causal edges (phase 1)
  ORC->>NW: build NewsDigest (effective weights)
  ORC->>MR: analyze_sentiment(NewsDigest)
  MR->>GW: (impl) route → adapter → vendor
  GW-->>EL: Call Record (provider, model, hashes, tokens, cost, latency)
  GW-->>MR: sentiment scores
  MR-->>ORC: ReasoningResponse (sentiment)
  ORC->>SC: trend, risk, regime (det. confidence), MHI
  SC-->>ORC: State Vector
  ORC->>RE: evaluate regime-guarded rules (phase 2), merge
  ORC->>MR: synthesize(state + rules + sentiment)
  MR->>GW: route → adapter → vendor
  GW-->>EL: Call Record
  GW-->>MR: summaries, ordinal drivers, novelty, data-gaps
  MR-->>ORC: ReasoningResponse (synthesis)
  ORC->>GR: post-validate (schema/range/consistency/contradiction/grounding)
  GR-->>ORC: guardrail_flags[] + publish decision
  ORC->>DB: persist run_inputs + run_outputs + versions (+ Call Records already in EL)
  ORC-->>SCH: published (MarketStateRun)
```

## 2. Event run (macro release) — with debounce

```mermaid
sequenceDiagram
  autonumber
  participant OP as Operator / POST /v1/events
  participant ETR as Event Trigger
  participant SCH as Scheduler
  participant ORC as Orchestrator
  participant EL as Event Log

  OP->>ETR: submit Macro Event (event_id, consensus, actual)
  ETR->>ETR: compute surprise = actual − consensus (deterministic)
  ETR->>ETR: debounce (≤1 event run / 30 min; aggregate)
  alt within cooldown
    ETR-->>OP: accepted, aggregated (debounced_events++)
  else cooldown elapsed
    ETR->>SCH: request event run
    SCH->>ORC: start run (trigger_type=event, trigger_detail{event_id, debounced_events})
    Note over ORC,EL: same lifecycle as scheduled run (diagram 1),<br/>rules trigger on surprise; event-driven regime possible
    ORC-->>SCH: published (event MarketStateRun, ≤5 min from trigger)
  end
```

## 3. Degraded run (all providers fail) — ADR-011

```mermaid
sequenceDiagram
  autonumber
  participant ORC as Orchestrator
  participant MR as MarketReasoner (port)
  participant GW as LLMGateway
  participant P1 as Provider A
  participant P2 as Provider B
  participant EL as Event Log
  participant SC as ScoringEngine/Regime
  participant GR as Guardrails
  participant AL as Alerts
  participant DB as Persistence

  ORC->>MR: synthesize(...)
  MR->>GW: route
  GW->>P1: call (retry×N)
  P1-->>GW: fail (timeout)
  GW-->>EL: Call Record (outcome=timeout)
  GW->>P2: failover call (retry×N)
  P2-->>GW: fail (5xx)
  GW-->>EL: Call Record (outcome=error)
  Note over GW: all configured providers exhausted / circuit-open
  GW-->>MR: degraded marker (no fabricated fields)
  MR-->>ORC: degraded (synthesis fields absent)
  ORC->>SC: deterministic outputs already computed (unaffected)
  ORC->>GR: validate; add degradation flag; honest-absence check
  GR-->>ORC: guardrail_flags[+degraded], publish
  ORC->>AL: alert "LLM fallback engaged"
  ORC->>DB: persist Degraded Run (is_degraded=true, deterministic fields present)
```

## 4. Replay run — lossless, offline

```mermaid
sequenceDiagram
  autonumber
  participant RH as ReplayHarness
  participant EL as Event Log
  participant CORE as Deterministic Core
  participant RP as ReplayProvider
  participant CMP as Comparator

  RH->>EL: load run_inputs + call_records + versions (run_id or range)
  RH->>CORE: feed immutable inputs (pin config/rule versions)
  RH->>RP: register recorded Call Records (no network)
  CORE->>RP: (LLM call) request
  RP-->>CORE: recorded response (byte-identical)
  CORE-->>RH: recomputed MarketStateRun
  RH->>CMP: compare vs stored run_outputs (deterministic fields)
  CMP-->>RH: identical? (nightly regression fails build on unexplained diff)
  Note over RH: ablation A→D selects which stages run (rules-only … full)
```

## 5. Outcome recording (async +6h / +24h)

```mermaid
sequenceDiagram
  autonumber
  participant SCH as Scheduler (delayed job)
  participant OR as OutcomeRecorder
  participant MD as Market data (later prices)
  participant CFG as Asset config (ATR-relative noise)
  participant DB as Persistence

  SCH->>OR: horizon matured for run_id (6h / 24h)
  OR->>MD: fetch realized prices at horizon
  OR->>CFG: read ATR-relative noise threshold (k·ATR%)
  OR->>OR: compute realized_return, realized_volatility, label (up/down/noise)
  OR->>DB: insert outcomes (run_id, symbol, horizon, ...)
  Note over OR,DB: outcomes feed Evaluation (Brier, accuracy vs baselines)
```

## 6. News ingestion → sentiment input

```mermaid
sequenceDiagram
  autonumber
  participant FEED as External news feed
  participant NS as NewsSource
  participant DB as news_items
  participant ORC as Orchestrator
  participant EL as Event Log
  participant NW as NewsWeigher
  participant MR as MarketReasoner

  FEED->>NS: pre-collected items (Q3)
  NS->>DB: persist NewsItems (source, published_at, source_quality)
  ORC->>NS: request items for this run window
  NS-->>ORC: NewsItems
  ORC-->>EL: snapshot news the run saw (run_inputs)
  ORC->>NW: compute effective_weight = source_quality × relevance × recency_decay
  NW-->>ORC: NewsDigest (weighted, ranked)
  ORC->>MR: analyze_sentiment(NewsDigest)
```

---

**Note on determinism in diagrams:** every diagram routes LLM interaction through **MarketReasoner → LLMGateway
only** — no component ever calls a vendor directly. Every LLM call emits a **Call Record** to the Event Log.
These two facts are what make diagrams 1–3 replayable as diagram 4.
