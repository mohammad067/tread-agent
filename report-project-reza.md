# Market State Engine — Complete Technical Analysis

> This report is based **only** on the source code currently in the repository
> (`c:/Users/Moham/OneDrive/Desktop/tread-agent`). It describes what actually exists, not what is
> planned. Where the code intentionally uses mocks or placeholders, that is stated explicitly.
> Package root: `src/market_state_engine/`. Python 3.10+ (targets 3.12).

---

## 1. Project Purpose

**What it does.** The Market State Engine produces a **"Market State"** — a structured, versioned,
schema-validated JSON snapshot of market conditions for **six assets** (BTC, ETH, GOLD, WTI, USD_IRR,
TOTAL_MCAP) plus a **Global Regime**. Each run computes, per asset: a `trend` score `[-1,1]`, a
`risk` score `[0,1]`, a deterministic `confidence` `[0,1]`, an optional LLM `sentiment` `[-1,1]`, a
`market_health_index` (0–100 integer), activated rules, causal links, and (when an LLM is available)
a Persian-language human summary. The Global Regime is classified as `risk_on` / `risk_off` /
`transition` / `event_driven`.

**What problem it solves.** It turns raw market inputs (prices, indicators, fear-greed, dominance,
total market cap, macro events, news) into an **explainable and auditable** market read where **all
numbers are computed deterministically** by code, and a language model is used only for three narrow
jobs: news sentiment, novelty flags, and human-readable Persian summaries. Every run is **replayable**
(inputs, prompts, and LLM responses are stored) and **versioned** (rulebook, weights, prompts,
provider, model, pricing, pipeline). It is explicitly **not a price predictor and not an advisor** —
every response carries a disclaimer.

**Who consumes its outputs.** It is **API-only, no front-end** (ADR-012). Consumers are programmatic
clients reading the REST API: a "latest state" reader, run-history/audit readers, and operators who
submit macro events or trigger runs. The `MarketStateRun` JSON contract *is* the product surface.

**Is it production-ready?** **No — not for live market operation.** The full software architecture is
implemented and tested end to end (389 tests pass; ruff + mypy-strict + import-linter all green), and
it can serve a real HTTP API over a real SQLite/Postgres database. However, **it currently runs
entirely on deterministic mock market data** and there is **no scheduler process, no live data-source
adapters, and no live-provider execution exercised**. See §11 and §12 for the precise gap list.

**What is implemented (working, tested):**
- Deterministic core: features, indicators, changes, surprise, decay, trend/risk/confidence/MHI
  scoring, regime classification, YAML rule engine with sign-off gate + conflict resolution, news
  weighting, guardrails, and deterministic state assembly.
- LLM layer: `MarketReasoner` port, `LLMGateway` with retry/timeout/failover/circuit-breaker/health/
  routing, OpenAI/Claude/Gemini adapters (live path present, lazily loaded), Fake + Replay providers,
  prompt builder, structured-output validation, versioned cost, Call Record capture.
- Pipeline orchestrator (10-stage flow), a manual/replay scheduler, persistence (SQLAlchemy + Alembic
  migration), FastAPI app with all endpoints + observability, DI composition root, structured logging.
- Evaluation framework: OutcomeRecorder, ReplayHarness, metrics, evaluation-correctness checks,
  ablation runner, reporting, production validation.

**What is intentionally mocked / placeholder:**
- **All market data** comes from `ingestion/mocks/mock_sources.py` via `app/ingest.py`. There are
  **no real data-source adapters** (no kifpool, no crypto-venue, no news feed, no macro-event feed).
- The **default ingest** injects one hard-coded CPI macro event and **no news items**.
- The **scheduler has no cron/timer driver** — runs must be triggered manually or via the API.
- Live LLM calls are **never exercised in code paths that run** (all real-provider client-construction
  paths are marked `# pragma: no cover`); tests use Fake/Replay providers only.

---

## 2. Complete Architecture

The system is a strict layered (clean-architecture) design. Dependency direction is enforced by
**six import-linter contracts** in `pyproject.toml` (all currently "kept"). The deterministic core
never imports I/O, frameworks, or vendor SDKs; the pipeline reaches the LLM only through a port;
persistence and evaluation are leaf/downstream layers.

### Layers and packages

**A. Domain core — `core/`** (pure, no I/O)
- **Why it exists:** the single home for ubiquitous-language types and the frozen contract.
- **Receives / produces:** nothing at runtime — it defines types. `models.py` holds the
  `MarketStateRun` Pydantic contract (`extra="forbid"`, alias `global`) and its parts (`Asset`,
  `Scores`, `Regime`, `Driver`, `RuleActivation`, `CausalLink`, `Global`, `FearGreed`, `GuardrailFlag`,
  `Versions`, `TriggerDetail`, `Price`, `Changes`, `Indicators`, …). `dtos.py` holds internal DTOs
  (`RawSnapshot`, `FeatureSet`, `AssetFeatures`, `NewsDigest`, `NewsItem`, `MacroEvent`, `AssetScores`,
  `RegimeResult`, …). `enums.py`, `run_context.py` (injected clock + previous regime + versions),
  `hashing.py` (`content_hash` = SHA-256 over `json.dumps(sort_keys, separators=(",",":"))`),
  `serialization.py` (`prune_none`), `errors.py`.
- **Called by:** every other layer.

**A2. Features — `features/`** (pure math)
- **Why:** all arithmetic lives here so "the LLM never computes a number." `engine.py`'s
  `FeatureEngine.compute(price_snaps, indicator_snaps, global_snaps, events, ctx) → FeatureSet`.
  `indicators.py` (RSI-14 Wilder, EMA, MACD state, EMA-20/50 state, ATR%, volume ratio), `changes.py`
  (6h/24h/7d/30d horizon changes; bar cadence `{6h:1,24h:4,7d:28,30d:120}`), `surprise.py`
  (`surprise = actual − consensus`, sigma, proximity, event feature), `decay.py`
  (`0.5 ** (elapsed / half_life)`).
- **Receives:** `RawSnapshot`s + config. **Produces:** a `FeatureSet`. **Called by:** the orchestrator.

**A3. Rules — `rules/`** (pure)
- **Why:** deterministic, auditable, human-authored rulebook. `loader.py` loads `rules/**.yaml`,
  enforces the **ADR-008 hard sign-off gate** (`reviewed_by: senior_trader`, non-empty
  `economic_rationale`) + surprise-var and gold-CPI lints (raises `RuleGateError`). `matcher.py`
  evaluates surprise conditions via regex (no `eval`) and applies regime guards. `conflict.py`
  resolves opposing effects on the same asset (OQ-3: highest strength wins; equal + opposing →
  neutral + flag). `engine.py`'s `RuleEngine.match(events, regime) → (activations, conflict_flags)`.
- **Receives:** `EventFeature`s + regime. **Produces:** per-asset `Activation`s + conflict flags.
- **Called by:** the orchestrator.

**A4. News — `news/`** (pure)
- `weigher.py`'s `NewsWeigher.weigh(run_id, items, target_assets, now) → NewsDigest`, computing
  `effective_weight = source_quality × relevance × recency_decay`, ranked. `relevance.py` (trusted
  upstream score, else asset-tags=1.0 / keyword=0.5 / none=0.0). **Called by:** the orchestrator.

**A5. Scoring — `scoring/`** (pure)
- `engine.py`'s `ScoringEngine.score(feature_set, previous_state, sentiment) → ScoringResult`.
  `trend.py`, `risk.py`, `confidence.py` (`0.5·completeness + 0.5·concordance`), `mhi.py`
  (config-weighted 0–100, drops sentiment when absent), `regime.py` (`classify(...)` — event-driven on
  material surprise, else risk_on/off/transition from average trend/risk over regime-sensitive assets;
  USD_IRR excluded as `regime_sensitivity: low`). **Called by:** the orchestrator.

**A6. Guardrails — `guardrails/`** (pure)
- `checks.py` + `engine.py`'s `validate(run) → GuardrailResult(flags, publish)`. Checks: degraded
  honesty, dangling causal link (blocks publish if CRITICAL), trend/indicator contradiction, regime-
  change flag consistency. **Called by:** the orchestrator (post-assembly).

**Assembly — `assembly/`** (pure)
- `deterministic_state.py`'s `DeterministicStateAssembler.assemble(...) → MarketStateRun`. Builds a
  **schema-valid degraded run** (LLM fields null/absent, `is_degraded=True`, `degraded_run` flag). The
  orchestrator later *enriches* this base with LLM output (never modifying the assembler).

**B. Reasoning (LLM) layer — `reasoning/`** (provider-agnostic; the only place a vendor SDK may live)
- `port.py` — `MarketReasoner` Protocol: `analyze_sentiment` / `synthesize` → response | `DegradedMarker`.
- `gateway.py` — `LLMGateway` implements the port; owns routing/retry/timeout/failover/circuit-breaker/
  health/Call-Record capture/cost/degrade. **Receives** a `ReasoningRequest`; **produces** a validated
  response or a `DegradedMarker`. **Called by** the orchestrator (via the port only).
- `registry.py` + `provider_config.py` (load/validate `providers.yaml`), `prompt_builder.py`
  (versioned/hashed neutral prompts), `structured_output.py` (validate against
  `reasoning_response.v1.json`), `pricing.py` (versioned cost table), `integration.py`
  (`build_gateway` / `build_replay_gateway` facade), `replay.py` (`verify_replay`,
  `build_replay_adapters`).
- `adapters/` — `base.ProviderAdapter` interface; `openai_provider.py`, `claude_provider.py`,
  `gemini_provider.py` (live; SDKs lazily imported), `fake.py`, `replay.py`, `factory.py`
  (config-name → adapter class), `_support.py` (`load_sdk` lazy importer + neutral system prompt).
- `reliability/` — `retry.py`, `timeout.py`, `circuit_breaker.py`, `health.py`, `router.py`.

**C. Ingestion — `ingestion/`** (I/O boundary, mock-only today)
- `base.py` — Protocol source ports: `PriceSource`, `IndicatorInputSource`, `FearGreedSource`,
  `DominanceSource`, `TotalMcapSource`, `NewsSource`, `EventSource`. `mocks/mock_sources.py` — the
  only concrete implementations. **No real adapters exist.**

**D. Persistence — `persistence/`** (leaf I/O)
- `models.py` (7 SQLAlchemy tables), `session.py` (`Database`, engine, `StaticPool` for `:memory:`,
  `resolve_url` from config/env), `repositories.py` (`RunRepository`, `CallRecordRepository`,
  `EventLogRepository`, `NewsRepository`, `RuleActivationRepository`). **Receives** contract dicts;
  **produces** rows/reads. **Called by** the runner and the API.

**E. Pipeline — `pipeline/`** (orchestration; owns sequencing)
- `orchestrator.py` (`PipelineOrchestrator.run(ctx, ingest) → PipelineResult`), `runner.py`
  (`RunService.execute` — persists everything + records events + idempotency), `scheduler.py`
  (`Scheduler` — assigns run identity, prevents overlap, scheduled/manual/replay modes), `events.py`
  (`EventRecorder`). **Called by** the composition root / API.

**Observability — `observability/`** — `logging.py` (structlog JSON; no `print`), `metrics.py`
(in-process counter/gauge registry, Prometheus text render).

**App / DI — `app/`** — `container.py` (`build_container` composition root), `ingest.py` (default mock
ingest provider), `main.py` (ASGI entrypoint: `market_state_engine.app.main:app`).

**G. API — `api/`** — `app.py` (`create_app(container)` — all endpoints), `envelope.py` (data+meta
envelope + error body), `security.py` (static API-key auth).

**F. Evaluation — `evaluation/`** (downstream tooling) — `outcomes.py`, `replay_harness.py`,
`metrics.py`, `engine.py`, `ablation.py`, `validation.py`, `reporting.py`, `schema_registry.py`.

### Dependency flow (runtime)

```
HTTP client
   │
   ▼
api/app.py  ──reads──►  persistence/repositories  ──►  DB (SQLite/Postgres)
   │ (POST /v1/runs:trigger)
   ▼
pipeline/scheduler ─► pipeline/runner (RunService) ─► pipeline/orchestrator
                                                          │
   ingestion (mock) ──IngestBundle──────────────────────►│
                                                          ├─► features ─► scoring ─► rules ─► news ─► guardrails ─► assembly   (deterministic core)
                                                          └─► reasoning/port ─► LLMGateway ─► adapters ─► (Fake/Replay today; live OpenAI/Claude/Gemini if wired)
                                                          │
                                            runner persists ─► run / run_inputs / run_outputs / call_records / rule_activations / event_log
```

Import rules enforced: `core` imports no I/O; compute layers never reach ingestion/persistence/
reasoning/pipeline/api; reasoning never reaches compute/pipeline/api; persistence reaches nothing above
it; **pipeline reaches the LLM only via `MarketReasoner`** (never the gateway impl or adapters — the
gateway is wired in `app/container.py`); nothing imports `evaluation`.

---

## 3. Complete Execution Flow

The lifecycle for one run is driven by `Scheduler.trigger()` → `RunService.execute()` →
`PipelineOrchestrator.run()`. Below, each stage names **where the object is created**.

**Trigger** — `pipeline/scheduler.py::Scheduler.trigger(mode)`
- Acquires a non-reentrant `threading.Lock` (non-blocking). If already held → raises `OverlapError`
  (overlap prevention). Creates the **`RunContext`** here: `run_id` = supplied or a fresh ULID
  (`new_run_id()`), `run_sequence` from an injected counter, `trigger_type` = `EVENT` for manual else
  `SCHEDULED`, `now` = injected clock, `previous_state` = injected provider, `versions` = injected.
- Calls the injected **`ingest_provider(ctx)`** to build the **`IngestBundle`** (created in
  `app/ingest.py::mock_ingest_provider` today), then `RunService.execute(ctx, ingest)`.

**RunService.execute** — `pipeline/runner.py`
- Clears the gateway Call-Record **sink**. Opens a DB session. Creates an **`EventRecorder`** and
  **`RunRepository`**. **Idempotency:** if `run_id` already exists → records a `scheduler` event and
  returns a no-op `RunSummary`. Else records a `run_start` (or `replay`) event, then calls
  `orchestrator.run(ctx, ingest)`.

**Ingestion** — the `IngestBundle` was already fetched by the ingest provider (price/indicator/global
`RawSnapshot`s, `MacroEvent`s, and `news_items`). Today this is deterministic mock data.

**Feature engine** — `orchestrator.run` stage 3: `FeatureEngine.compute(...)` creates the
**`FeatureSet`** (per-asset indicators, changes, ATR%, volume ratio, event features/surprises).

**News processing** — creates the **`NewsDigest`** via `NewsWeigher.weigh(run_id, news_items,
asset_symbols, ctx.now)` (deterministic `effective_weight`, ranked).

**LLM #1 (Sentiment)** — stage 5, *before* scoring. Builds a **`ReasoningRequest`** (job=`sentiment`,
payload = assets + `news_digest`, constraints language `fa`, grounding true, schema ref) and calls
`reasoner.analyze_sentiment(request)`. Returns a `SentimentResponse` or `None` (on `DegradedMarker`).
A `sentiment_map` (`dict[symbol → float]`) is derived.

**Scoring** — stage 6: `ScoringEngine.score(feature_set, previous_state, sentiment_map)` creates the
**`ScoringResult`** (per-asset `AssetScores` trend/risk/sentiment/confidence + `market_health_index`,
and the regime). Note: MHI is computed with sentiment folded in here.

**Regime classification** — inside `ScoringEngine.score`, `regime.classify(...)` creates the
**`RegimeResult`** (state, previous_state, changed_this_run, confidence, computed drivers).

**Rule engine** — stage 4/6b (regime-guarded rules resolved now that regime is known):
`RuleEngine.match(feature_set.event_features, regime_state)` creates the per-asset **`Activation`**s and
`conflict_findings` (mapped to `GuardrailFlag(code="rule_conflict")`).

**State assembly** — stage 9(assembly): `DeterministicStateAssembler.assemble(ctx, features, scoring,
activations, conflict_flags, price_snaps, global_snaps)` creates the **base `MarketStateRun`** — a
schema-valid **degraded** document (sentiment null, no summaries, `is_degraded=True`, `degraded_run`
flag).

**LLM #2 (Synthesis)** — stage 7: builds a `ReasoningRequest` (job=`synthesis`, payload = a
`state_vector` derived from the base run + the sentiment) and calls `reasoner.synthesize(...)` →
`SynthesisResponse` or `None`.

**Compose** — `orchestrator._compose(base, sentiment_map, synthesis)` folds LLM output into the run via
`model_copy` (adds `scores.sentiment`, `human_summary_fa`, `novelty_flags`); sets
`is_degraded = (synthesis is None or sentiment is None)`. The deterministic assembler is never mutated.

**Guardrails** — stage 8: `guardrail_validate(run) → GuardrailResult`; if flags differ, re-attach via
`model_copy`. Produces the final **`MarketStateRun`** + a publish decision. Returns a `PipelineResult`.

**Persistence** — back in `RunService.execute`, the run is JSON-normalized
(`json.loads(json.dumps(to_contract_dict()))` so enums serialize to their string values), then written
**in this order**: `runs` (`add_run`), `run_inputs` (`add_inputs`, with a serialized snapshot + a
content hash), `run_outputs` (`add_output`, with an output hash), `rule_activations` (`add_for_run`).
Then the Call-Record sink is drained: for each record, a `provider_call` event is recorded and the
record is inserted into `call_records` with a fresh ULID `call_id`. Finally a `degraded` event (if
degraded) and a `run_finish` event are recorded. Returns a **`RunSummary`**.

**API → response** — a consumer later reads the persisted document: `GET /v1/state/latest` (or
`/v1/runs/{id}`) → `RunRepository.latest()/get()` → wrapped in the `data + meta` envelope (with
`disclaimer`, `is_degraded`, `schema_version`) → JSON response. **No computation happens on the request
path**; the API only reads stored documents.

---

## 4. API Endpoints

All endpoints are implemented in `api/app.py` inside `create_app(container)`. Auth is enforced by
`api/security.py` reading environment variables `MSE_API_READ_KEY` and `MSE_API_WRITE_KEY` (header
`x-api-key`). **Read auth is "open" if no read key is configured** (dev default); **write endpoints
require `MSE_API_WRITE_KEY` to be set or they return 503**.

| Method / Path | Where | Calls | Returns | Reads stored? | Runs pipeline? | Auth |
|---|---|---|---|---|---|---|
| `GET /v1/state/latest` | `state_latest` | `RunRepository.latest()` | Latest `MarketStateRun` in `data`+`meta` (with `is_degraded`) | **Yes** | No | read key (open if unset) |
| `GET /v1/runs/{run_id}` | `run_by_id` | `RunRepository.get(run_id)` | That run's `MarketStateRun`; 404 if unknown | **Yes** | No | read |
| `GET /v1/runs?trigger_type=&limit=&cursor=` | `runs_range` | `RunRepository.list_runs(...)` | Paginated list of runs (`meta.pagination`) | **Yes** | No | read |
| `GET /v1/runs/{run_id}/inputs` | `run_inputs` | `RunRepository.get_inputs(run_id)` | Immutable input snapshot (raw_snapshots, snapshot_hash, data_gaps, deviation_flags); 404 if unknown | **Yes** | No | read |
| `GET /v1/runs/{run_id}/calls` | `run_calls` | `CallRecordRepository.list_for_run(run_id)` | List of Call Records for the run | **Yes** | No | read |
| `GET /v1/meta/versions` | `meta_versions` | reads container config | Active versions (schema/pipeline/rulebook/mhi_weights/source_quality/half_lives) | Config only | No | read |
| `POST /v1/events` | `submit_event` | validates + computes surprise | `{event_id, accepted, surprise}` — surprise computed **server-side** (`actual − consensus`); 422 on unknown `event_type` | No | No | **write** (503 if key unset; 403 if read key used) |
| `POST /v1/runs:trigger` | `trigger_run` | `container.scheduler.run_manual()` | `{run_id, status}`; 409 on `OverlapError` | No | **Yes — executes a full run** | **write** |
| `GET /v1/health` | `health` | — | `{status: ok}` in envelope | No | No | none |
| `GET /health/live` | `liveness` | — | `{status: alive}` | No | No | none |
| `GET /health/ready` | `readiness` | opens a DB session, `RunRepository.latest()` | `{status: ready}` (200) or `{status: not_ready}` (503 if DB down) | Yes (probe) | No | none |
| `GET /metrics` | `metrics` | `Metrics` + `EventLogRepository.count()` | Prometheus-format text incl. `event_log_entries` | Yes | No | none |

**Important:** `POST /v1/runs:trigger` is the **only** endpoint that executes the pipeline, and it
calls `run_manual()` (trigger_type = `EVENT`). There is **no endpoint or process that runs on a
schedule** — `POST /v1/events` records/echoes the event and computes surprise but **does not itself
trigger a run** in the current code. Error contract (`api/security.py` + handlers): 401 unauthorized,
403 forbidden (read key on write), 404 not_found, 422 invalid_request, 409 conflict, 503 unavailable.

---

## 5. Data Sources

**Today, every market input is a deterministic MOCK.** The default ingest provider used by the ASGI
app is `app/ingest.py::mock_ingest_provider`, which builds an `IngestBundle` from the classes in
`ingestion/mocks/mock_sources.py`. The dev environment config declares `ingestion.mode: mock`.

| Source (Protocol in `ingestion/base.py`) | Concrete impl today | Type | What it returns |
|---|---|---|---|
| `PriceSource` | `MockPriceSource` | **Mock/Static** | A generated OHLCV-ish series per symbol (`base − 0.5·i + 2·sin(i/3)`), fixed `as_of` |
| `IndicatorInputSource` | `MockIndicatorInputSource` | **Mock/Static** | Same generated series feeding indicators |
| `FearGreedSource` | `MockFearGreedSource` | **Mock/Static** | Fixed value (24 in default wiring) |
| `DominanceSource` | `MockDominanceSource` | **Mock/Static** | Fixed BTC dominance (56.8) |
| `TotalMcapSource` | `MockTotalMcapSource` | **Mock/Static** | Fixed total mcap (3.91e12) |
| `NewsSource` | `MockNewsSource` (exists, **not wired into default ingest**) | **Mock** | A supplied list of `NewsItem`s |
| `EventSource` | `MockEventSource` (exists, **not wired into default ingest**) | **Mock** | A supplied list of `MacroEvent`s |

The default `mock_ingest_provider` hard-codes **one** macro event (`us_cpi`, consensus 0.3, actual 0.45
→ surprise +0.15) and passes **no news items**. `MockNewsSource`/`MockEventSource` exist but are not
used by the default wiring.

**Ingest providers that currently exist:** only the mocks above (plus the test harness variants). The
production wiring seam is `ingest_provider: Callable[[RunContext], IngestBundle]`, injected into
`build_container`.

**Ingest providers that are MISSING (no code):**
- Live crypto price sources (median-across-venues, deviation flags — ADR-009).
- The **kifpool USD/IRR** adapter (the frozen design's `priceSellIRT` / IRT source).
- Live fear-greed / dominance / total-mcap sources.
- A **news feed reader** (`NewsSource` real adapter) — no crawler/feed integration.
- A **macro-event feed / manual-entry persistence path** (the API echoes events but does not persist
  them into `macro_events` — no such table exists, see §7).

**How a real provider would replace the current one:** implement a class satisfying the relevant
Protocol in `ingestion/base.py` (e.g. `fetch(symbol, ctx) → RawSnapshot`), then write an
`ingest_provider(ctx) → IngestBundle` that calls the real sources and pass it to `build_container(...,
ingest_provider=real_provider)` (or change `app/main.py::build_default_container` to use it). **No core
code changes are required** — the FeatureEngine and scoring consume `RawSnapshot`/`MacroEvent`/
`NewsItem` regardless of source. This is the intended seam (the mock is injected, not hardcoded into
business logic).

---

## 6. LLM Integration

**Where the LLM is called.** Only through the `MarketReasoner` port, only from the orchestrator, at
exactly two stages: `analyze_sentiment` (stage 5) and `synthesize` (stage 7). The production
implementation is `reasoning/gateway.py::LLMGateway`.

**When it is called.** Once per run for sentiment (before scoring) and once for synthesis (after
assembly). Each call independently degrades on failure without aborting the run.

**Which objects are sent.** A `ReasoningRequest` (Pydantic, schema-mirrored): `run_id`, `job`
(`sentiment`|`synthesis`), a `payload`, and `constraints` (`language: "fa"`, `grounding: True`,
`output_schema_ref`, `max_tokens`, `temperature: 0`). Sentiment payload = `{assets, news_digest}`;
synthesis payload = `{state_vector, sentiment}` where `state_vector` is derived from the assembled run.

**What prompts are built.** `reasoning/prompt_builder.py::PromptBuilder` loads a versioned template
from `prompts/{job}/vN.md`, substitutes `{{placeholder}}` tokens (deterministically serialized), and
computes `prompt_hash = content_hash(text)` over the **neutral** text (identical across vendors). The
two templates are `prompts/sentiment/v1.md` and `prompts/synthesis/v1.md` (Persian instructions; the
sentiment prompt asks for a per-asset sentiment score in `[-1,1]` from news only; the synthesis prompt
asks for Persian human summaries + ordinal drivers with a grounding constraint).

**How providers are selected.** From configuration only (`config/models/providers.yaml`). The
`ProviderRegistry` returns enabled providers **sorted by `(priority, name)`** — the failover chain.
The `Router` orders them: `priority` (default) or `weighted` (a deterministic seed fraction from
`sha256(run_id)` picks the first, remainder by priority). The gateway walks the chain: for each
provider it checks the circuit breaker, applies the retry + timeout policy, calls the adapter,
validates structured output, records a Call Record, and returns the first success. If all fail (or the
chain is empty), it returns a `DegradedMarker` — it never raises.

**What ReplayProvider does.** `reasoning/adapters/replay.py::ReplayProvider` serves **recorded Call
Records** through the same adapter interface — indexed by `prompt_hash`, consumed in recorded order.
On a recorded success it re-serializes the stored response canonically (so parse + hash reproduce
byte-identically) and returns the recorded tokens/finish_reason; on a recorded timeout/error it
re-raises the matching exception so failover replays identically. Unknown prompt hash → `ProviderCallError`.

**What FakeProvider does.** `reasoning/adapters/fake.py::FakeProvider` serves **canned** values you
configure at construction (fixed text/result, a results queue, or a forced exception) and records the
`(prompt, params)` it received. It is the offline test double; it has no notion of recorded history.

**What happens when no provider exists.** Two guards. (1) `ProvidersConfig` requires at least one
provider — an empty list fails validation at load (`ProviderConfigError`). (2) At runtime, if
`enabled_providers()` is empty, the router returns an empty chain and the gateway returns a
`DegradedMarker(reason="no enabled providers configured")`. In both the "all providers fail" and "no
provider" cases the pipeline still completes and produces an honest **degraded** `MarketStateRun`.

**Can it currently call a real LLM?** **Architecturally yes; operationally not as wired.** The three
real adapters (`openai_provider.py`, `claude_provider.py`, `gemini_provider.py`) implement the full
live path: they lazily import the vendor SDK (`_support.load_sdk` via `importlib`, only inside
`_get_client()`), read the API key from `os.environ[api_key_env]` (the env-var *name* comes from
`providers.yaml`), construct the vendor client, call the API, and map the response into the neutral
`RawProviderResult`. **However:** (a) the vendor SDK packages are **not installed**, (b) those
client-construction code paths are marked `# pragma: no cover` and are **never exercised by tests**,
and (c) the default app wiring (`app/main.py`) does not force live providers (the factory builds
adapters with no injected client, so a real call would be attempted only if a request reached the
gateway with SDKs + keys present). To make a real LLM call: install the SDK (`openai` / `anthropic` /
`google.generativeai`), set the env var named in `providers.yaml`, keep that provider `enabled: true`,
and issue a run. `config/environments/dev.yaml` declares `llm.mode: mock`, signaling the intended dev
default is offline.

---

## 7. Persistence

Implemented with SQLAlchemy 2 (`persistence/models.py`) + one Alembic migration
(`migrations/versions/0001_initial.py`). JSON columns use a portable variant (`JSON` on SQLite,
`JSONB` on Postgres). Dialect is chosen by environment config (`dev` = SQLite). **Seven tables exist:**

| Table | Purpose | Key columns (types) | Write pattern |
|---|---|---|---|
| `runs` | Run identity + all versions + status | `run_id` (CHAR26 PK), `run_sequence`, `trigger_type`, `trigger_detail`(JSON), `generated_at`, `schema_version`, `pipeline_version`, `provider_version?`, `model_version?`, `prompt_sentiment_version`, `prompt_synthesis_version`, `rulebook_version`, `mhi_weights_version`, `pricing_version?`, `status`, `is_degraded` | insert (status/is_degraded may update) |
| `run_inputs` | Immutable input snapshot (1:1) | `run_id` (PK/FK), `raw_snapshots`(JSON), `snapshot_hash`, `data_gaps`(JSON), `deviation_flags`(JSON), `ingested_at` | **append-only** |
| `run_outputs` | Immutable full `MarketStateRun` (1:1) | `run_id` (PK/FK), `market_state_run`(JSON), `guardrail_flags`(JSON), `output_hash`, `persisted_at` | **append-only** |
| `call_records` | Per-LLM-attempt replay/cost/metrics | `call_id`(PK), `run_id`, `llm_job`, `attempt_index`, `provider`, `model_id`, `prompt_version`, `prompt_hash`, `rendered_prompt`(Text), `response?`(JSON), `response_hash?`, `latency_ms`, `input_tokens?`, `output_tokens?`, `estimated_cost?`, `retries`, `finish_reason?`, `outcome`, `created_at` | **append-only** |
| `event_log` | Lifecycle-event trace | `event_seq`(PK autoincr), `run_id?`, `event_type`, `payload`(JSON), `created_at` | **append-only** |
| `news_items` | Ingested news records | `news_id`(PK), `source`, `url?`, `title`, `published_at`, `source_quality?`, `raw`(JSON), `ingested_at` | upsert (idempotent) |
| `rule_activations` | Queryable projection of a run's activated rules | `activation_seq`(PK autoincr), `run_id`, `symbol`, `rule_id`, `strength`, `horizon`, `decay_remaining`, `created_at` | **append-only** |

Indexes (migration 0001): `runs(run_sequence)`, `runs(generated_at)`, `runs(trigger_type)`,
`call_records(run_id)`, `call_records(provider, created_at)`, `event_log(run_id)`,
`event_log(event_type)`, `rule_activations(run_id | symbol | rule_id)`.

**What gets stored.** Per run: the identity/versions row, the exact input snapshot + its hash, the full
`MarketStateRun` output + its hash, one Call Record per LLM attempt (including failures), the rule
activations, and a chronological event trace (`run_start`, `provider_call`, `degraded`, `run_finish`,
etc.). The `event_type` string is free-form.

**Replay data.** `run_inputs.raw_snapshots` (price/indicator/global snapshots + events) +
`call_records` (rendered prompt + response + hashes) + all version columns — the replay backbone.

**Call records.** Persisted append-only in `call_records`, one per attempt, with `estimated_cost`
derived from the versioned pricing table when tokens are present.

**Outcome records.** The **Milestone-6 `OutcomeRecorder`** writes typed execution outcomes (success /
degraded / replay / evaluation / provider / validation) into the **existing `event_log`** table as
`execution_outcome` rows — **not** a dedicated table.

**What is NOT stored (no table exists):**
- **`macro_events`** — the frozen design references a manual macro-event table; it is **not
  implemented**. `POST /v1/events` computes surprise and echoes it but persists nothing.
- **`outcomes`** — realized-return outcomes at +6h/+24h (the "did the market move" evaluation) — **no
  table, not implemented** (the M6 OutcomeRecorder records *execution* outcomes, not *realized-return*
  outcomes).
- **`news_items`** — the table exists and a `NewsRepository.upsert` exists, but the pipeline does **not
  currently persist news** (the default ingest passes no news, and `run_inputs` does not include news).
- `rules_versions`, `config_versions`, `evaluation_reports` — referenced in the frozen DB design but
  **not implemented** as tables.

---

## 8. Replay Framework

Replay is implemented twice, at two levels, both reusing the same primitives:

**LLM-call replay** (`reasoning/replay.py` + `adapters/replay.py`): `build_replay_adapters(records)`
builds one `ReplayProvider` per recorded provider; `verify_replay(recorded, replayed)` compares the
**replay-critical fields** (`run_id, llm_job, attempt_index, provider, model_id, prompt_version,
prompt_hash, response_hash, outcome`) — **excluding** `latency_ms` and `created_at` (environmental) —
and returns `ReplayVerification(matched, compared, diffs)`.

**Full-pipeline replay** (`evaluation/replay_harness.py::ReplayHarness`), step by step:
1. **`load(db, run_id)`** — reads `run_inputs.raw_snapshots`, the stored `run_outputs` document, and
   the run's `call_records`. Rebuilds the `IngestBundle` from the stored snapshots
   (`_rebuild_ingest`), reconstitutes `CallRecord`s, derives `previous_state` from the stored regime.
   Raises `ValueError` if inputs/output are missing.
2. **`replay(loaded)`** — builds a container whose providers are **`ReplayProvider`s only** (no live
   call possible), re-runs the pipeline with the **same `run_id`** (so prompt hashes match), reads the
   replayed output, and computes two fingerprints on both stored and replayed docs.
3. Returns a `ReplayResult` with: `deterministic_match` (core fingerprint equal — the guarantee),
   `full_deterministic_match` (core + MHI), `call_records_match` (`verify_replay`),
   `reproduced_is_degraded`, and `ok = deterministic_match`.

**Exactly what is reproduced.** The **`core_fingerprint`** — regime (state/previous/changed/confidence/
drivers) + per-asset `trend`, `risk`, `confidence`, `activated_rules`, `causal_links`. This is the
frozen replay guarantee (ADR-011 DR-4): the deterministic core reproduces **byte-identically**. When
every prompt input is persisted (a news-free run), the **full** fingerprint (incl. MHI) and the **Call
Records** also reproduce.

**Limitations (documented in the code and `docs/architecture/evaluation-framework.md`):**
- `run_inputs` does **not persist news items** (news feeds only the LLM sentiment prompt, never a
  deterministic number). So replaying a **news-bearing** run reproduces the core identically, but its
  sentiment prompt hash differs → the `ReplayProvider` misses → sentiment degrades on replay → MHI
  shifts. Hence `deterministic_match` deliberately tracks the sentiment-independent **core**, not MHI.
  A news-free run reproduces fully including Call Records. This is a **persistence scope boundary, not
  a defect** — widening it would require persisting news in `run_inputs` (a schema/persistence change).

---

## 9. Evaluation Framework

Implemented in `evaluation/` (Milestone 6). All components are read-and-recompute over stored data;
none contacts a live provider.

**OutcomeRecorder** (`outcomes.py`) — records typed execution outcomes to `event_log` as
`execution_outcome` rows. `OutcomeKind` = `success | degraded | replay | evaluation | provider |
validation`, with convenience methods (`record_success`, `record_degraded`, `record_replay`,
`record_provider`, `record_evaluation`, `record_validation`) and `outcomes_for_run(run_id)`.

**ReplayHarness** (`replay_harness.py`) — §8.

**Metrics** (`metrics.py`) — pure aggregation over stored Call Records + runs:
- `collect_call_metrics(call_records)` → `MetricsSummary`: `total_calls`, `success_rate`,
  `timeout_rate`, `error_rate`, `avg_latency_ms`, `total_retries`, `total_input_tokens`,
  `total_output_tokens`, `total_estimated_cost`, and per-provider `ProviderMetrics` (calls, successes,
  success_rate, total_retries, avg_latency_ms, input/output tokens, estimated_cost).
- `collect_run_rates(runs)` → degraded/published counts + `degraded_rate`.
- `collect_replay_rate(list[bool])` → `replay_success_rate`.
- All **operational-only** (a hard wall keeps provider metrics out of model-quality evaluation —
  ADR-007 D-7).

**Evaluation Engine** (`engine.py`) — seven correctness checks, each returning a `CheckResult`
(name, passed, detail, failures); aggregated by `EvaluationSummary`:
1. `check_replay_correctness` — the deterministic core reproduced (uses `ReplayResult`).
2. `check_provider_correctness` — every Call Record has a valid outcome and coherent response shape
   (success ⇒ non-null response; non-success ⇒ null response).
3. `check_deterministic_consistency` — recomputing the fingerprint twice is identical.
4. `check_schema_validity` — the stored run validates against `market_state_run.v1.0.0.json`.
5. `check_contract_validity` — the run carries all required contract fields.
6. `check_degraded_correctness` — a degraded run shows honest absence (no sentiment/summary) + the
   `degraded_run` flag.
7. `check_prompt_consistency` — identical rendered prompts always carry the same `prompt_hash`.

**Ablation Runner** (`ablation.py`) — runs three variants through the **real** orchestrator with a
variant `MarketReasoner` double:
- `DETERMINISTIC_ONLY` (no LLM — both calls degrade),
- `DETERMINISTIC_SENTIMENT` (sentiment only; synthesis degrades),
- `FULL` (both succeed).
`AblationComparison.core_fields_identical` asserts the sentiment-independent core is identical across
all variants (only the LLM-fed layer — MHI, summaries — changes). Corresponds to the frozen B/C/D
ablation bands.

**Production Validation** (`validation.py`) — AST + schema checks aggregated into
`ValidationReport.production_ready`:
- `check_architecture_compatibility(pkg_root)` — core imports no I/O/vendor; pipeline reaches the LLM
  only via the port; no vendor SDK imported outside `adapters/`.
- `check_schema_compatibility(schemas_dir)` — every frozen schema is a valid JSON Schema.
- `check_provider_independence(pkg_root)` — the reasoning public surface names no vendor; no top-level
  vendor import outside adapters.

**Reporting** (`reporting.py`) — five JSON-serializable report builders: `replay_report`,
`evaluation_report`, `provider_report`, `degradation_report`, `production_validation_report`.

**Schema registry** (`schema_registry.py`) — offline `referencing` + `jsonschema` registry over
`schemas/` for cross-file `$ref` resolution.

**What is NOT here (vs. the frozen evaluation design):** directional accuracy vs persistence /
always-neutral baselines, Brier score, and calibration buckets are **not implemented** — those depend
on realized-return `outcomes` at +6h/+24h, and neither the `outcomes` table nor a realized-return
recorder exists. The M6 evaluation validates **correctness/replay/consistency**, not market predictive
accuracy.

---

## 10. Configuration

All configuration is loaded through `config/loader.py` (`load_config_bundle`, `load_env_config`) into
typed Pydantic models (`config/models.py`), fail-fast on error. No values are hardcoded in business
logic.

**Environments — `config/environments/{dev,staging,prod}.yaml`.** `dev.yaml`: `env: dev`,
`database.dialect: sqlite`, `ingestion.mode: mock`, `llm.mode: mock`, `scheduler.scheduled_cron:
"0 */6 * * *"`, `scheduler.event_cooldown_minutes: 30`, `budget.monthly_llm_budget: 0.0`. (staging/prod
declare their own dialects; the DSN for Postgres is read from an env var named in config —
`session.resolve_url`.)

**Providers — `config/models/providers.yaml`.** `routing.strategy: priority`,
`routing.degrade_after_all_fail: true`. Defaults: temperature 0, max_tokens 1024, timeout 20s,
retries 2, exponential backoff (400ms→4000ms), circuit breaker (threshold 5 / window 120s / half-open
60s). Providers: **openai** (enabled, priority 1, weight 60, `OPENAI_API_KEY`, model `gpt-5.5`);
**anthropic** (enabled, priority 2, weight 40, `ANTHROPIC_API_KEY`, model `claude-sonnet-5`);
**gemini** (**disabled**, priority 3, weight 0, `GOOGLE_API_KEY`, model `gemini-2.5-pro`).

**Pricing — `config/models/pricing.v1.yaml`.** Versioned per-model input/output rates per
`unit_tokens` (1000), with a `default` fallback → drives `estimated_cost` on Call Records.

**SQLite.** Dev uses SQLite; the ASGI app path is `MSE_SQLITE_PATH` (default `mse_dev.db` at repo root).
In-memory SQLite uses a `StaticPool` so all sessions share one connection.

**Asset YAML — `config/assets/{btc,eth,gold,wti,usd_irr,total_mcap}.yaml`.** Per-asset symbol,
display name, `asset_class`, `regime_sensitivity` (USD_IRR = low), decimals, trading hours,
staleness threshold, noise threshold, indicator list, rules dir, price-source/source config.

**Other YAML:** `config/weights/mhi_weights.v1.yaml` (MHI weights summing to 1.0 — validated),
`config/sources/source_quality.v1.yaml` (per-source quality + default), `config/decay/half_lives.v1.yaml`
(per-event-type news half-lives + rule half-lives).

**Schemas — `schemas/`.** `market_state_run.v1.0.0.json` (the public contract) + 11 internal schemas
in `schemas/internal/` (`raw_snapshot`, `feature_set`, `news_digest`, `reasoning_request`,
`reasoning_response`, `rule_activation`, `causal_link`, `state_vector`, `call_record`,
`degraded_marker`, `rule`). These are frozen JSON Schemas validated in CI.

**Prompts — `prompts/`.** `sentiment/v1.md` and `synthesis/v1.md` — versioned, hashed, vendor-neutral
Persian-language templates.

**Rulebooks — `rules/`.** `VERSION` (a SemVer string) + `rules/global/*.yaml`
(`cpi_hot_risk_assets_bearish.yaml`, `cpi_soft_risk_assets_bullish.yaml`). Each rule must pass the
ADR-008 sign-off gate (`reviewed_by: senior_trader`, non-empty `economic_rationale`) or loading fails.

**Migrations — `migrations/` + `alembic.ini`.** Alembic env + `0001_initial` creating all 7 tables +
indexes; portable JSON variant; URL injected at runtime (no secret in the ini).

---

## 11. Current Missing Production Pieces

Based **only** on the repository:

### Implemented (working, tested)
- Deterministic core (features / rules / news / scoring / regime / MHI / confidence / guardrails /
  assembly).
- LLM abstraction: port, gateway with retry/timeout/failover/circuit-breaker/health/routing, three
  vendor adapters (live path present but SDK-less and untested), Fake + Replay providers, prompt
  builder, structured-output validation, versioned cost, Call Record capture.
- Pipeline orchestrator (10-stage), `RunService` persistence, manual/replay scheduler with overlap
  prevention + idempotency.
- Persistence (7 tables) + Alembic migration + repositories; SQLite dev, Postgres-capable.
- FastAPI app (all read endpoints, two operational writes, observability), envelope, API-key auth.
- Structured logging, in-process metrics.
- Evaluation framework (OutcomeRecorder, ReplayHarness, metrics, evaluation checks, ablation,
  reporting, production validation).
- CI gates: ruff, ruff-format, mypy-strict, import-linter (6 contracts), pytest+coverage (389 tests).

### Partially implemented
- **LLM live execution** — real adapters exist and are architecturally complete, but vendor SDKs are
  not installed, the client-construction paths are `# pragma: no cover`, and no test exercises a live
  call. Reachable only if SDKs + keys are present at runtime.
- **News pipeline** — `NewsWeigher`, `NewsItem`, `MockNewsSource`, and a `news_items` table +
  `NewsRepository` exist, but the default ingest passes no news and `run_inputs` does not persist news;
  no real news feed adapter.
- **Macro events** — surprise math + `MacroEvent` DTO + `POST /v1/events` (echo + surprise) exist, but
  there is **no `macro_events` table** and events are not persisted or used to trigger runs.
- **Scheduler** — a `Scheduler` with `run_scheduled()`/`run_manual()`/`run_replay()` and overlap
  prevention exists, and `scheduled_cron` is in config, but **nothing invokes `run_scheduled()` on a
  timer** — no cron/APScheduler/background process is wired.
- **Observability** — structured logging + a `/metrics` endpoint exist, but there is no external
  metrics backend, alerting, tracing, or dashboards.

### Missing (no code)
- **Live market-data adapters:** crypto price venues (median-across-venues + deviation flags), the
  kifpool USD/IRR source, live fear-greed / dominance / total-mcap.
- **News crawler / feed reader** (real `NewsSource`).
- **Macro-event feed / persistence** (`macro_events` table + real ingestion).
- **A running scheduler / cron process** (6-hour cadence + event debounce).
- **Realized-outcome recording** (`outcomes` table + a +6h/+24h returns recorder) and the
  **predictive-accuracy evaluation** that depends on it (directional accuracy vs baselines, Brier,
  calibration).
- **Additional DB tables** referenced in the frozen design but not implemented: `outcomes`,
  `macro_events`, `rules_versions`, `config_versions`, `evaluation_reports`.
- **Deployment artifacts:** no Dockerfile, no container/compose, no infra-as-code, no
  `.github/workflows` deploy job (CI only runs quality gates), no rate-limiter implementation
  (the design mentions token-bucket rate limiting; the code has none).
- **Secrets management / production auth hardening** beyond static API keys read from env.

---

## 12. Current Production Readiness

**Can this repository, alone, operate on live market data? No.**

The software is a complete, well-tested application skeleton with a fully working deterministic core,
a resilient provider-agnostic LLM layer, real persistence, a real HTTP API, and an evaluation
framework. It starts as an ASGI app (`uvicorn market_state_engine.app.main:app`), serves every
endpoint, and executes end-to-end runs. **But it processes deterministic mock data and has no
mechanism to obtain, schedule, or persist live market inputs.** Precisely why, from the code:

1. **No live data sources.** The only ingestion implementations are the deterministic mocks
   (`ingestion/mocks/mock_sources.py`), wired via `app/ingest.py::mock_ingest_provider`. There is no
   HTTP/feed code anywhere under `ingestion/` (verified: no `requests`/`httpx`/`urllib`/kifpool
   references). Every price/indicator/fear-greed/dominance/mcap value is generated or fixed.

2. **No scheduler process.** `Scheduler.run_scheduled()` exists but nothing calls it on a timer;
   `scheduled_cron` is an unused config string. Runs happen only via `POST /v1/runs:trigger`
   (`run_manual`) or a direct call. There is no 6-hour cadence and no event-debounce driver.

3. **No live LLM execution exercised.** The vendor adapters are complete but their SDKs aren't
   installed and their live client-construction paths are never run (all `# pragma: no cover`). With no
   provider reachable, runs would produce **honest degraded** states (deterministic numbers only, no
   sentiment/summaries) — which is correct ADR-011 behavior, but means the LLM value-add is not
   currently active.

4. **No macro-event or news ingestion path to production data.** `POST /v1/events` echoes an event and
   computes surprise but persists nothing and triggers nothing; there is no `macro_events` table and no
   real news feed.

5. **No realized-outcome loop.** There is no `outcomes` table and no recorder of realized returns, so
   the system cannot yet evaluate predictive accuracy on live data (only replay/consistency/schema
   correctness).

6. **No deployment/ops layer.** No Dockerfile, no deploy pipeline, no rate limiter, no external
   metrics/alerting.

**Exactly what still needs to be connected to run on live data (no redesign — using the existing
seams):**
- Implement real classes satisfying the `ingestion/base.py` Protocols (price venues, kifpool USD/IRR,
  fear-greed, dominance, total-mcap, news feed, macro events) and a real `ingest_provider(ctx) →
  IngestBundle`; inject it via `build_container(..., ingest_provider=...)` / `app/main.py`.
- Add a scheduler driver (cron/APScheduler/background task) that calls `Scheduler.run_scheduled()` on
  the configured cadence and routes `POST /v1/events` into the event-triggered run path.
- Install a vendor SDK, set the `api_key_env` env var, and keep a provider `enabled: true` so the
  gateway performs live LLM calls (or leave degraded-only, which is a valid mode).
- (For predictive evaluation) add an `outcomes` table + a realized-return recorder and the accuracy/
  Brier/calibration metrics.
- (For ops) add deployment artifacts, a Postgres target, secrets management, and rate limiting.

**Bottom line:** the deterministic engine, LLM resilience layer, persistence, API, replay, and
evaluation-correctness tooling are **implemented and green**. What remains for live operation is the
**data-and-schedule perimeter** (live sources, a scheduler process, macro-event/news persistence,
realized-outcome tracking) and the **operational perimeter** (deployment, live-provider execution,
ops tooling) — all of which attach to existing, clearly-defined seams without changing the core.
