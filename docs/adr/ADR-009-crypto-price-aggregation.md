# ADR-009: Multi-venue crypto price aggregation policy (median, deviation flags)

- **Status:** Accepted (2026-07-19)
- **Deciders:** Senior Blockchain Engineer, Senior Trader
- **Related:** ADR-004; challenges A8 (index series), A9 (stablecoin methodology), A10 (USDT proxy)

## Context
Crypto prices differ across venues (spread, wicks, print anomalies, outlier venues). Silently averaging
divergent sources hides data-integrity problems and can move a score on a bad print. BTC Dominance also flips
meaning depending on whether stablecoins are in the denominator.

## Decision
- **Median across venues** for crypto spot prices, with `min_sources` and `max_deviation_pct` per asset config.
- **Cross-source deviation > threshold (e.g., 0.5%) → FLAG, never silently average** (`deviation_flags` in
  `run_inputs`). Wick/print anomaly filtering before aggregation.
- **BTC Dominance / Total Market Cap** use **one fixed, documented stablecoin methodology** pinned in
  `config/sources/` (state which — e.g., dominance excluding stablecoins — with rationale). They are
  **index/context series** with a reduced indicator set (A8), not the full technical suite.
- **USD/IRR (kifpool `priceSellIRT`)** is internally a **USDT/IRT proxy** (A10), returned in **IRT/Toman**.
  Its proxy nature is documented **internally only** (dictionary/ADR-014) and **not surfaced** in the API/UI
  (no `proxy_note` field). Its USDT-depeg/cash-premium **divergence risk** remains an engineering monitoring
  concern (cross-source/deviation checks) even though it is not a payload disclosure.

## Alternatives Considered
- **Mean across venues**: rejected — outliers/bad prints distort the mean; median is robust.
- **Single "best" venue**: rejected — single point of failure and venue bias.
- **Silently average divergent sources**: rejected outright — violates the data-integrity principle (§7).

## Consequences
- (+) Robust prices; divergence surfaced not hidden; dominance is reproducible; USD/IRR honestly labeled.
- (−) Requires ≥ `min_sources` venues to aggregate; if too few, the price is marked stale/gapped rather than
  fabricated — accepted (degrade-not-fail).
