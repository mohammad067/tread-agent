# Domain Dictionary — Ubiquitous Language

> **Binding from Milestone 0.** Every identifier, schema field, API path, log message, ADR, and document
> uses these **exact** terms. A synonym in code or docs is a defect. Persian glosses are the approved
> translations for `human_summary_fa` and UI copy.
> **Version:** 0.4.0 (Milestone 0 draft; frozen alongside the schema in Milestone 2).
> **0.2.0 change:** added the External LLM Provider abstraction section and ownership-language ban (decision D4).
> **0.3.0 change:** added provider resilience/observability terms (Provider Registry, Provider Priority,
> Weighted Routing, Provider Health Monitor, Circuit Breaker, Call Record, RenderedPrompt, Estimated Cost,
> Provider Metrics) to align with the frozen ADR-007/ADR-011 architecture.
> **0.4.0 change (ADR-014):** Human Summary is **Persian-only** (`human_summary_fa`, no EN in v1.0.0); USD/IRR
> is **IRT (Toman)**; the USDT/IRT proxy nature is **internal-only** (not surfaced in API/UI).

## How to read this table

- **Term** — the canonical English identifier (also the code/schema token where applicable).
- **Definition** — precise, implementation-neutral meaning.
- **Persian gloss** — approved translation for UI/summary use.
- **Appears in** — where the term is authoritative (Schema field / API / Config / Log / Rule / Doc).

---

## Core state concepts

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Market State** | The complete, structured, explainable snapshot of market conditions produced by one Run. The product's central artifact. Not a prediction. | وضعیت بازار | Schema (`MarketStateRun`), API, Docs |
| **MarketStateRun** | The versioned JSON document conforming to `market_state_run.v1.0.0.json` that encodes one Market State. | سند وضعیت بازار | Schema (root), API |
| **State Vector** | The deterministic numeric core of a Market State: the per-asset and global scores (trend, risk, sentiment, MHI) plus regime, from which explanations are synthesized. | بردار وضعیت | Docs, Scoring |
| **Regime** (Global Market Regime) | The market-wide condition classification: one of `risk_on`, `risk_off`, `transition`, `event_driven`. Computed first; assets are analyzed in its context (except low-sensitivity assets). | رژیم بازار | Schema (`regime.state`), Rule, Log |
| **Regime Sensitivity** | Per-asset degree to which an asset's analysis is governed by the Global Regime: `high` \| `medium` \| `low`. USD/IRR is `low` and analyzed on domestic drivers. | حساسیت به رژیم | Config (asset), Schema (`regime_sensitivity`) |
| **Market Health Index (MHI)** | An integer 0–100 summarizing an asset's condition, computed as a **versioned weighted projection** of the State Vector. Weights live in `config/weights/`, never in code or prompts. | شاخص سلامت بازار | Schema (`market_health_index`), Config |

## Scores & signals

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Trend Score** | Deterministic scalar in `[-1, 1]` computed in code from indicators (RSI, MACD state, EMA relation, multi-horizon changes). Positive = uptrend. Never LLM-set. | امتیاز روند | Schema (`scores.trend`), Scoring |
| **Risk Score** | Deterministic scalar in `[0, 1]` computed in code from volatility (ATR%), event proximity, and volume anomalies. Higher = more risk. Never LLM-set. | امتیاز ریسک | Schema (`scores.risk`), Scoring |
| **Sentiment Score** | Scalar in `[-1, 1]` produced by **LLM Call #1** (the configured External LLM Provider) from the weighted News Digest. The only score the provider sets. | امتیاز احساسات | Schema (`scores.sentiment`), LLM Call #1 |
| **Confidence** (System Confidence) | A scalar in `[0, 1]` expressing the **system's** confidence in a score or classification. **Deterministically derived** (e.g., signal concordance, data completeness, self-consistency divergence). **Never a probability** and never labeled as one. | اطمینان سیستم | Schema (`confidence`), UX |
| **Indicator** | A deterministic technical measure computed from price/volume: `rsi_14`, `macd_state`, `ema_20_50`, `atr_pct`, `volume_ratio_20d`. | اندیکاتور | Schema (`indicators`), Features |

## Explanation & causality

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Driver** | A factor cited as materially shaping a score or regime. Carries a `weight_type`. | محرک | Schema (`drivers`) |
| **Computed weight** | A driver weight that is a **real percentage** from the scoring formula (`weight_type: computed`). Honest, reproducible. | وزن محاسبه‌شده | Schema (`weight_type`) |
| **Ordinal weight / level** | A driver importance **estimated by the configured External LLM Provider** and expressed as an **ordinal level** — `dominant` \| `major` \| `moderate` \| `minor` — never a fabricated percentage (`weight_type: ordinal`). | سطح ترتیبی | Schema (`level`) |
| **Causal Link** | A `from → to` edge with a `direction`, attributed to an activated rule (`via_rule`). A **presentation artifact** assembled from rule edges — never a reasoning mechanism. | پیوند علّی | Schema (`causal_links`) |
| **Human Summary** | The natural-language description+explanation of an asset's state, produced by **LLM Call #2** in the same JSON. Describes and explains; **never advises**. **Persian only** — `human_summary_fa` (ADR-014). No English field in v1.0.0; EN is a possible future MINOR additive field. | خلاصه انسانی | Schema (`human_summary_fa`) |
| **Novelty Flag** | An LLM-raised marker that something falls **outside the rule set** (a dynamic the rules don't cover). Feeds the rule-authoring backlog. | نشانه نوظهور | Schema (`novelty_flags`) |
| **Data Gap** | A declared missing/stale/excluded input (e.g., `informal_overnight_quotes_excluded`). Runs **degrade with gaps, never fail silently**. | خلأ داده | Schema (`data_gaps`), Log |

## Rules & events

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Rule** | A versioned YAML entry (id, trigger, effects, half-life, source, `economic_rationale`, `reviewed_by`) mapping a condition to per-asset effects. Only **activated** rules enter prompts. | قاعده | Rule (`rules/`), Config |
| **Rule Activation** | The event of a Rule's trigger condition being satisfied in a Run, yielding effects + causal edges injected into the state. | فعال‌سازی قاعده | Schema (`activated_rules`), DTO |
| **Economic Rationale** | The mandatory market-truth justification on every Rule, approved by the Senior Trader persona (`reviewed_by: senior_trader`). No rule ships without it. | توجیه اقتصادی | Rule (`economic_rationale`) |
| **Surprise** | The signed difference between an event's **actual** and **consensus** (e.g., `surprise_core_mom = actual − consensus`, in the event's natural units). Macro rules trigger on **surprise, not raw actuals**. | سورپرایز / غافلگیری | Schema (`trigger_detail`), Rule, Event |
| **Macro Event** | A scheduled economic release (US CPI, FOMC, US NFP for MVP) carrying `consensus` and `actual`, from which Surprise is computed. Entered manually (Q4). | رویداد کلان | Config, Schema (`trigger_detail`) |
| **Effect** | One `{asset, direction, strength, horizon}` consequence declared by a Rule. `direction` ∈ {bullish, bearish, neutral}; `strength` ∈ {dominant, major, moderate, minor}. | اثر | Rule (`effects`) |
| **Half-life** | The time (hours) over which a Rule's / news item's influence decays to half. Per-event-type. | نیمه‌عمر | Rule, Config (`decay/`) |
| **Decay** | The deterministic time-based reduction of a Rule's or news item's weight, governed by Half-life. `decay_remaining` ∈ `[0,1]`. | واپاشی / زوال | Schema (`decay_remaining`), Features |

## News weighting

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **News Item** | A single pre-collected news record consumed from the external feed (Q3). Input to the NewsWeigher. | خبر | DTO (`NewsItem`) |
| **Effective Weight** | The deterministic news weight: `source_quality × relevance × recency_decay`. Computed **in code**; the External LLM Provider consumes it and never assigns it. | وزن مؤثر | Schema/DTO, NewsWeigher |
| **Source Quality** | A configured trust score per news source (`config/sources/source_quality`). | کیفیت منبع | Config |
| **News Digest** | The weighted, ranked bundle of News Items handed to LLM Call #1. | چکیده اخبار | DTO (`NewsDigest`) |

## External LLM provider abstraction

> **Foundational stance (decision D4):** This project **does not own, train, fine-tune, or host any language
> model.** Every LLM interaction is a call to a **configured External LLM Provider** through a provider
> abstraction. The rest of the system never knows which provider is used. Language understanding is an
> *implementation dependency*, not a capability we own.

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **External LLM Provider** | A third-party language-model service (e.g., OpenAI, Anthropic Claude, Google Gemini, DeepSeek, Grok, or any future vendor) reached over an API. The **configured** provider performs the three LLM jobs. We own the integration, never the model. | ارائه‌دهنده‌ی بیرونی مدل زبانی | Config (`models/providers`), Schema (`versions.provider`) |
| **LLM Gateway** | The single component through which **all** LLM calls flow. It selects the configured provider, applies retry/timeout, fails over across providers, enforces structured output, and records provider/model/prompt-hash/response for replay. The core never calls a provider directly. | دروازه‌ی مدل زبانی | Reasoning layer |
| **MarketReasoner** | The core-facing **port** (interface) the pipeline depends on: structured `ReasoningRequest` in → structured `ReasoningResponse` out. The core depends only on this interface and has **zero** provider knowledge; the LLM Gateway implements it. | استدلال‌گر بازار | DTO, Reasoning layer |
| **Provider Adapter** | A per-vendor implementation behind the LLM Gateway (`OpenAIProvider`, `ClaudeProvider`, `GeminiProvider`, …) translating the neutral request/response to/from that vendor's API. Adding a provider = **one new adapter, zero business-logic changes**. | تطبیق‌گر ارائه‌دهنده | Reasoning layer (`adapters/`) |
| **Provider Configuration** | Runtime-selectable settings — `provider`, `model`, `temperature`, `timeout`, retry policy, fallback order — that change which provider/model is used **without code changes**. Versioned; recorded per Run. | پیکربندی ارائه‌دهنده | Config (`models/providers.yaml`) |
| **Provider Failover** | The Gateway's policy of trying the next configured provider when one fails. If **all** configured providers fail, the Run becomes a **Degraded Run** (rule-engine-only), never a failed Run. | جایگزینی ارائه‌دهنده | Reasoning layer, Error handling |
| **Degraded Run** | A Run where the LLM-dependent fields are absent because every configured provider failed after retries/failover. The **deterministic core still produces a valid Market State**; the output is flagged degraded with an alert. | اجرای تنزل‌یافته | Schema (`guardrail_flags`), Pipeline |
| **LLM Job (the only three)** | The exhaustive set of tasks delegated to the External LLM Provider: (1) interpret unstructured news → Sentiment; (2) detect **Novelty** outside the rule set; (3) synthesize **Human Summaries**. The provider does **no** market arithmetic. | وظایف مدل زبانی | Docs, ADR-001/007 |
| **Provider Registry** | The Gateway's startup/reload load of enabled providers + their policies from `providers.yaml`. Defines the routing set; holds **no** secrets (keys come from ENV). | دفتر ثبت ارائه‌دهندگان | Reasoning, Config |
| **Provider Priority** | Ordered failover preference among providers; the chain tries healthy providers in ascending priority. | اولویت ارائه‌دهنده | Config (`providers.yaml`) |
| **Weighted Routing** | A routing strategy distributing first-pick calls across healthy providers by configured `weight` (cost/latency balancing, A/B), then falling through by priority on failure. | مسیریابی وزنی | Config, Router |
| **Provider Health Monitor** | Rolling per-provider success/latency/timeout tracking that gates routing eligibility and feeds metrics. **Operational only — never influences market outputs.** | پایش سلامت ارائه‌دهنده | Reasoning, Observability |
| **Circuit Breaker** | Resilience mechanism that trips a sustained-failing provider out of rotation, then half-open-probes to restore it — without aborting the pipeline. | مدارشکن | Reasoning |
| **Call Record** | The per-attempt Event-Log entry for every LLM call: provider, model_id, prompt_version, prompt_hash, response_hash, response, latency, input/output tokens, estimated_cost, retries, finish_reason, outcome. The unit of replay, cost, and metrics. | رکورد فراخوان | Persistence (Event Log), ADR-007 |
| **RenderedPrompt** | The provider-neutral, application-rendered prompt text handed to an adapter — **byte-identical regardless of vendor**, so `prompt_hash` matches across providers. | پرامپت رندرشده | Reasoning (PromptBuilder), `prompts/` |
| **Estimated Cost** | The per-call cost computed automatically from token counts × a **versioned price table** (`config/models/pricing`), recorded per Run so historical cost stays reproducible. No manual accounting. | هزینه برآوردی | Call Record, Cost governance |
| **Provider Metrics** | Operational aggregates from Call Records (success/timeout/failure rate, avg latency/tokens/cost, fallback frequency, breaker state). Drive dashboards/alerts and routing — **never** market scores. | سنجه‌های ارائه‌دهنده | Observability |

## Runs, triggers, evaluation

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Run** | One execution of the pipeline producing one MarketStateRun. Identified by `run_id` (ULID) and ordered by `run_sequence`. | اجرا | Schema (`run_id`), Log |
| **Trigger Type** | Why a Run happened: `scheduled` (6h cron) or `event` (macro-event path). Evaluated in **separate buckets**. | نوع تریگر | Schema (`trigger_type`) |
| **Debounce / Cooldown** | Event-path rate control: max **one event Run per 30 minutes**; concurrent events aggregate (`debounced_events`). | فرونشانی | Pipeline, Schema (`trigger_detail`) |
| **Observation** | The framing of every output: a market **observation**, not advice or prediction. | مشاهده | Compliance, Disclaimer |
| **Outcome** | The realized market result attached to a Run **after the fact** (+6h/+24h returns vs Noise Threshold, realized volatility). | پیامد / نتیجه | Schema/DB (`outcomes`), OutcomeRecorder |
| **Noise Threshold** | The per-asset band below which a realized move is **noise, not signal**, for outcome labeling. Proposed **ATR-relative** (`k · ATR%`) with a floor (challenge A5). Trader-defined. | آستانه نویز | Config (asset), OutcomeRecorder |
| **Replay** | Re-running any pipeline **variant** offline over stored immutable inputs to reproduce or compare outputs. A design that breaks lossless replay is wrong. | بازپخش | ReplayHarness |
| **Ablation** | A pipeline **variant** for paired comparison: A rule-engine-only → B +deterministic-news → C +LLM-sentiment → D full. | تحلیل حذفی | Evaluation |
| **Event Log** | The append-only store of every Run's exact inputs, generated prompts (+ hashes), all versions, and full output. Losing it destroys replayability. | گزارش رویداد | Persistence |

## Crypto / data-integrity terms

| Term | Definition | Persian gloss | Appears in |
|------|------------|---------------|------------|
| **Venue Aggregation** | The policy for combining multiple exchange prices into one: **median across venues**, with cross-source deviation flags; never silent averaging of divergent sources. `venue_aggregation: "median_5"`. | تجمیع صرافی‌ها | Schema (`price.venue_aggregation`), ADR-009 |
| **BTC Dominance** | Bitcoin's share of Total Market Cap, under a **fixed, documented stablecoin methodology** (ADR-009). An index/context series, not a full technical asset. | تسلط بیت‌کوین | Schema (`global.btc_dominance`) |
| **Total Market Cap** | Aggregate crypto market capitalization (`TOTAL_MCAP`); an **index/context series** (challenge A8). | ارزش کل بازار | Schema (`global.total_market_cap_usd`) |
| **USDT/IRT Proxy** | The USD/IRR reference used in MVP: kifpool `priceSellIRT` (USDT sell price in **Toman/IRT**). Internally a **proxy** for USD/IRR that inherits USDT-depeg/cash-premium risk. **Internal-only (ADR-014):** the proxy nature is NOT surfaced in the API/UI — `USD_IRR` is presented plainly with `currency: "IRT"`. This term documents the engineering fact, not a payload field. | پروکسی تتر/تومان | Ingestion, internal note (not payload) |
| **Stale** | A price flagged `is_stale: true` because it is older than the asset's staleness threshold or the market is closed (e.g., `tehran_market_closed_weekend`). Displayed dimmed. | کهنه / منسوخ | Schema (`is_stale`), UX |

## Reserved (schema slots now, zero implementation in MVP)

| Term | Definition | Appears in |
|------|------------|------------|
| **Expectation Context** | Reserved slot fed by event surprises now; a real Expectation Layer (implied vol, basis, positioning) is Phase 4. | Schema (`global.expectation_context`) |
| **On-chain Context** | Reserved slot (owned by Senior Blockchain Engineer persona) for netflows, stablecoin supply, active addresses, MVRV-class metrics. Phase 3+. Value is `null` in MVP. | Schema (`global.onchain_context`) |

---

### Terms explicitly banned from user-facing surfaces
- "Prediction", "forecast", "buy/sell", "recommendation", "signal to trade", "probability" (for `confidence`).
  Use **Observation**, **Market State**, **System Confidence**. Enforced in `06-ux-content-requirements.md`
  and `07-compliance.md`.

### Terms banned from **all** documentation and code (ownership implication)
- **"our LLM", "our model", "our AI", "the model we trained", "internal model"** — the project owns **no**
  model. Use **"the configured External LLM Provider"**, **"the external language model"**, or **"the LLM
  Gateway"**. Any phrasing implying we host/train/own a model is a defect (decision D4).
