# Product Vision & Positioning

> **Milestone 0 deliverable.** One-page vision. Terms are used exactly as defined in
> [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

## The problem

People who need to understand markets — traders, analysts, and the developers who build tools for them —
are served by two bad options:

1. **Raw dashboards** dump numbers (prices, RSI, Fear & Greed) and leave the human to assemble meaning under
   time pressure. They show *what* without *why*, and they don't remember what they said yesterday.
2. **Black-box predictors** output a number or a "buy/sell" with no traceable reasoning, no audit trail, and
   no way to check whether they were right in a way that survives model changes.

Neither is **explainable**, **auditable**, or **scientifically evaluable**. When the state of the market
changes, neither can answer the one question that matters: *"What changed, and why?"* — with receipts.

## What we are building

A **Market State Engine** that produces a **Market State** — a structured, explainable, auditable snapshot
of market conditions — **every 6 hours**, plus **immediately after major macro events** (CPI/FOMC/NFP-class),
across six assets — **Bitcoin, Ethereum, Gold, Crude Oil (WTI), USD/IRR (Tehran parallel-market proxy), and
Crypto Total Market Cap** — plus a **Global Market Regime**.

Every Market State is:

- **Explainable** — key Drivers with honest weights (Computed percentages where real, Ordinal levels where
  estimated), and Causal Links traceable to versioned Rules.
- **Auditable & replayable** — every Run stores its exact inputs, generated prompts (hashed), and all
  versions, so any pipeline variant can be replayed offline over full history.
- **Scientifically evaluable** — every Run is later scored against realized Outcomes and against baselines,
  separated by Trigger Type, with Brier scores and calibration.

## What this product deliberately is **not**

(Ties to §3 System Boundaries. Reinforced in [07-compliance.md](07-compliance.md).)

- **Not a price predictor.** No forecasts, no price targets.
- **Not an advisor.** No buy/sell, no portfolio logic, no recommendations. It serves *pre-trade context*, it
  never advises. An investment decision layer is a **future layer above** the Market State, never inside it.
- **Not an autonomous agent.** The configured External LLM Provider is used as a pure function — structured
  request in, structured response out — with exactly three jobs: interpret unstructured news, flag novelty
  outside the rules, and synthesize explanations. All numbers are computed deterministically in code.
- **Not the owner of any model.** We do **not** own, train, fine-tune, or host a language model. Language
  understanding is an *implementation dependency*: every LLM call flows through a provider-agnostic **LLM
  Gateway** to a configured external provider (OpenAI, Claude, Gemini, DeepSeek, Grok, or any future vendor),
  swappable by configuration with zero code changes. If every provider fails, the deterministic core still
  produces a valid Market State (a Degraded Run).
- **Not a black box.** If a number can't be traced to a Rule or a formula, it doesn't ship.

## Why "explainable Market State" beats the alternatives

| Dimension | Raw dashboard | Black-box predictor | **Market State Engine** |
|-----------|---------------|---------------------|--------------------------|
| Answers "why?" | No | No | **Yes — drivers + causal links to versioned rules** |
| Auditable after the fact | No | No | **Yes — immutable input snapshots + prompt hashes** |
| Evaluable vs. reality | No | Sometimes (opaque) | **Yes — outcomes, baselines, Brier, calibration** |
| Survives model change | N/A | No (score meaning drifts) | **Yes — replay on identical inputs, deterministic core** |
| Consistent over time | No (stateless) | Varies | **Yes — versioned schema, run sequence, regime history** |
| Honest about uncertainty | No | Rarely | **Yes — system confidence + data gaps + novelty flags** |

The wedge is **trust through traceability**: not "trust the number," but "here is the number, here is the
rule that produced it, here is the input it saw, and here is how it scored against what actually happened."

## Primary consumers

1. **A frontend dashboard** — Timeline of Market States, per-asset cards, causal graph. Consumes the JSON
   contract only (we own the contract + a mock-serving endpoint, not the UI).
2. **The system's own evaluation pipeline** — replay, ablation, and calibration reporting.

## Vision success (what "good" looks like at MVP)

- A dashboard analyst opens the app after a CPI print and, **within minutes**, sees an updated Market State
  that explains the move in plain language tied to a named Rule.
- A developer integrates the JSON contract **without talking to us**, because the schema and its
  field-to-need mapping are documented.
- A quant can **replay** last month under a different pipeline variant and get a **paired Brier comparison**
  — because every Run kept its inputs.
- A desk trader reads the state as **pre-trade context** and never once mistakes it for advice, because the
  product's language never crosses that line.

## The long game (architecture must not block it)

The MVP is Phase 1 of a seven-phase roadmap (static rules → dynamic rules → deep news + on-chain →
expectation layer → portfolio intelligence → recommendation engine → autonomous intelligence). Every reserved
extension point (`expectation_context`, `onchain_context`, confidence calibration, rule migration to SQL)
exists so **no future phase requires a ground-up redesign**. The MVP earns the right to those phases by being
correct, auditable, and evaluable first.
