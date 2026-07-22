# Evaluation, Replay & Production-Validation Framework (Milestone 6)

> **Milestone 6 — production tooling.** This document describes the components added in Milestone 6.
> They are strictly **downstream** production tooling: they read the immutable Event Log and re-run
> pipeline variants offline through `ReplayProvider`, computing **no** market number and contacting
> **no** live provider. Nothing in the deterministic core, reasoning layer, persistence, pipeline,
> API, ADRs, or schemas is modified. Builds on [pipelines.md](pipelines.md) §5–7 and
> [module-catalog.md](module-catalog.md) §F.
> **Version:** 1.0.0

## 1. Where it sits

```
                 (reads, never writes market state)
Event Log  ──►  evaluation/  ──►  reports (dicts / JSON)
(run_inputs,     OutcomeRecorder · ReplayHarness · Metrics
 run_outputs,    EvaluationEngine · AblationRunner · Validation · Reporting
 call_records,
 event_log)
```

Maps to `src/market_state_engine/evaluation/`. A dedicated import-linter contract (**"Evaluation is
downstream — no lower layer imports it"**) enforces that no core/compute/reasoning/pipeline/
persistence/api module depends on `evaluation`; the tooling is strictly downstream of the system it
evaluates. It reuses existing abstractions — `verify_replay`, `build_replay_adapters`, `ReplayProvider`,
`PipelineOrchestrator`, the repositories, and the DI `Container` — with no reimplementation.

## 2. Components

| Component | File | Responsibility | Reuses |
|-----------|------|----------------|--------|
| **OutcomeRecorder** | `outcomes.py` | Persist a typed execution outcome (success / degraded / replay / evaluation / provider / validation) to the append-only `event_log` as `execution_outcome` rows. No schema change (event_type is free-form). | `EventLogRepository`, `Database` |
| **ReplayHarness** | `replay_harness.py` | Load a run's stored `run_inputs` + `call_records`, rebuild the `IngestBundle`, replay through `ReplayProvider`s (no live call), and verify equivalence. | `build_container`, `ReplayProvider`, `verify_replay` |
| **Metrics** | `metrics.py` | Aggregate latency, retries, provider success rate, degraded rate, replay success rate, token usage, and estimated cost from stored Call Records + runs. Operational-only (ADR-007 D-7). | Call Record / run dicts |
| **Evaluation Engine** | `engine.py` | Seven correctness checks: replay, provider, deterministic-consistency, schema, contract, degraded, prompt. | `ReplayHarness`, schema registry |
| **Ablation Runner** | `ablation.py` | Run the deterministic-only / +sentiment / full variants over identical inputs → directly comparable results. | `PipelineOrchestrator`, port DTOs |
| **Production Validation** | `validation.py` | Architecture / schema / provider-independence checks → a production-readiness verdict. | AST scan, `Draft202012Validator` |
| **Reporting** | `reporting.py` | Assemble the replay / evaluation / provider / degradation / production-validation reports as JSON-serializable dicts. | all of the above |
| **Schema registry** | `schema_registry.py` | Offline JSON-Schema loading with cross-file `$ref` resolution over the frozen `schemas/`. | `referencing`, `jsonschema` |

## 3. The replay guarantee (what "equivalent" means)

The frozen replay property (database.md §5, **ADR-011 DR-4**) is that the **deterministic core**
reproduces byte-identically — regime, per-asset trend/risk/confidence, activated rules, and causal
links. `ReplayHarness` verifies exactly this via a **core fingerprint** (`core_fingerprint`), and
exposes it as `ReplayResult.deterministic_match` (and `ok`).

Two finer distinctions, documented so the numbers are unambiguous:

- **`full_deterministic_match`** additionally includes `market_health_index`. MHI legitimately folds
  in sentiment (a real input to MHI), so it reproduces only when the **LLM leg** also reproduces.
- The LLM leg reproduces when every prompt input is present in `run_inputs`. In M5, `run_inputs`
  persists price/indicator/global snapshots + events but **not news items** (news feeds only the LLM
  sentiment prompt, never a deterministic number). A run whose sentiment consumed news therefore
  replays its **core** identically while its sentiment leg degrades on replay; a run with no news
  reproduces fully, including Call Records. This is a **persistence scope boundary, not a defect** —
  the frozen guarantee is about deterministic fields, and those always reproduce. Widening replay to
  the full LLM leg for news-bearing runs would require persisting news in `run_inputs`, a schema/
  persistence change out of scope for M6.

## 4. Ablation semantics

`AblationRunner` runs three variants through the **same** `PipelineOrchestrator` with a variant
`MarketReasoner` double:

| Variant | Sentiment | Synthesis | Result |
|---------|-----------|-----------|--------|
| `DETERMINISTIC_ONLY` | degraded | degraded | rules + scoring only (`is_degraded=true`) |
| `DETERMINISTIC_SENTIMENT` | present | degraded | scores reflect sentiment; no summaries |
| `FULL` | present | present | full run with summaries |

The deterministic core is identical across variants, so their **core fingerprints are identical**
(`AblationComparison.core_fields_identical`). Only the sentiment-fed layer (MHI, summaries) differs —
the ablation's whole point (F-9). This corresponds to the frozen A→D ladder's B/C/D bands.

## 5. Guarantees preserved (production-validation dimensions)

`validation.py` mechanically checks the frozen guarantees still hold: **architecture compatibility**
(core imports no I/O/vendor; pipeline reaches the LLM only via the port; no vendor SDK outside
adapters), **schema compatibility** (every frozen schema is a valid JSON Schema), **provider
independence** (the reasoning public surface names no vendor), plus per-run **schema/contract/replay/
deterministic** checks from the Evaluation Engine. Aggregated into `ValidationReport.production_ready`.

## 6. Offline & hermetic

Every component reads stored data or re-runs over stored inputs with `ReplayProvider`; **no live
provider is contacted** and no network is used (frozen invariants #6/#10). All time is injected, so
the tooling is deterministic in tests.
