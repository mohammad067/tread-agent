# Scoring Methodology (deterministic)

> **Milestone 3 design-before-code.** The exact deterministic formulas for trend, risk, system confidence,
> MHI, and regime. Contracts fix ranges/shapes; this document fixes the math. Every formula is pure and
> replay-reproducible, and defensible under Senior-Trader review (§7). No LLM input anywhere.
> **Version:** 1.0.0

## 0. Conventions
- All inputs come from the `FeatureSet` (indicators, changes, ATR%, volume ratio, event features) and config.
- Missing inputs contribute a neutral value and are recorded as data gaps; they never abort scoring.
- Outputs are clamped to their contract ranges.

## 1. Trend Score ∈ [-1, 1]
A weighted blend of momentum signals, each mapped to [-1, 1]:

| Signal | Mapping to [-1,1] | Weight |
|--------|-------------------|--------|
| `ema_20_50` | above_diverging +1.0, above_converging +0.5, crossing 0, below_converging −0.5, below_diverging −1.0 | 0.30 |
| `macd_state` | bullish_cross +1.0, bullish +0.5, neutral 0, bearish −0.5, bearish_cross −1.0 | 0.25 |
| `rsi_14` | `(rsi − 50) / 50` (so 0→−1, 50→0, 100→+1) | 0.15 |
| 24h change | `clamp(change_pct / SCALE_24H, −1, 1)`, `SCALE_24H = 5.0` | 0.15 |
| 7d change | `clamp(change_pct / SCALE_7D, −1, 1)`, `SCALE_7D = 15.0` | 0.15 |

`trend = clamp(Σ wᵢ·sᵢ / Σ wᵢ_present, −1, 1)`. Weights of missing signals are dropped and the sum
renormalized over present signals (so an index asset with only changes still scores). If no signal present →
`0.0`.

**Rationale:** trend structure (EMA/MACD) dominates; RSI and multi-horizon change confirm. Scales chosen so a
"normal" daily move is a fraction of full-scale, not saturating.

## 2. Risk Score ∈ [0, 1]
Higher = more risk. Blend of volatility, event proximity, and participation anomaly:

| Component | Mapping to [0,1] | Weight |
|-----------|------------------|--------|
| Volatility (`atr_pct`) | `clamp(atr_pct / ATR_FULL, 0, 1)`, `ATR_FULL = 5.0` | 0.50 |
| Event proximity | active event within `horizon`: `clamp(1 − |proximity_hours| / PROX_WINDOW, 0, 1)`, `PROX_WINDOW = 48.0`; 0 if no event | 0.30 |
| Volume anomaly (`volume_ratio_20d`) | `clamp((ratio − 1) / VOL_SPAN, 0, 1)`, `VOL_SPAN = 2.0` (only elevated volume adds risk) | 0.20 |

`risk = clamp(Σ wᵢ·rᵢ / Σ wᵢ_present, 0, 1)`. Missing components dropped and renormalized. No signal → `0.0`.

**Rationale:** ATR% is the primary risk driver; nearness to a macro event raises risk; abnormal volume signals
instability. All bounded so a single spike can't exceed 1.

## 3. System Confidence ∈ [0, 1] (deterministic — A2)
Confidence in an asset read from **signal concordance** and **data completeness** — never a probability, never
LLM-set.

- `completeness = present_signal_count / expected_signal_count` for the asset class (full assets expect 5
  indicator signals; index assets expect their reduced set).
- `concordance = 1 − dispersion`, where dispersion is the mean absolute deviation of the trend sub-signals
  (from §1) around their mean, normalized to [0,1] (agreeing signals → low dispersion → high concordance).
- `confidence = clamp(0.5·completeness + 0.5·concordance, 0, 1)`.

Stale price lowers completeness (a stale asset yields fewer fresh signals), so its confidence drops naturally.

**Rationale:** we are honest that confidence reflects *how much coherent evidence we have*, not the probability
of being right.

## 4. Market Health Index ∈ [0, 100] (integer)
A versioned weighted projection using `config/weights/mhi_weights` (weights sum to 1.0). Each component is
mapped to [0,1] "health" (higher = healthier), combined, then scaled to 0–100:

| Config weight key | Health mapping [0,1] |
|-------------------|----------------------|
| `trend` | `(trend + 1) / 2` |
| `risk` | `1 − risk` (lower risk = healthier) |
| `sentiment` | `(sentiment + 1) / 2` if present; **when sentiment is absent (no eligible news or degradation), this component is dropped and remaining weights renormalized** |
| `volatility` | `1 − clamp(atr_pct / ATR_FULL, 0, 1)` |

`mhi = round(100 · Σ wₖ·healthₖ / Σ wₖ_present)`.

**Rationale:** MHI is a config-owned projection (never hardcoded). Degraded runs drop the sentiment term and
renormalize so the index stays valid and honest without a fabricated sentiment.

## 5. Regime Classifier (deterministic, computed first — ADR-005)
Global regime from macro-style inputs, **not** crypto Fear & Greed (A6). Inputs: cross-asset aggregate trend
and risk (mean over regime-sensitive assets, i.e. excluding `regime_sensitivity: low`), and whether a recent
macro event is active.

Decision (evaluated in order):
1. If an event feature is active within its window **and** its |surprise| is material → `event_driven`.
2. Else compute `avg_trend` and `avg_risk` over regime-sensitive assets:
   - `avg_risk ≥ RISK_HI (0.6)` and `avg_trend ≤ −TREND_BAND (−0.2)` → `risk_off`.
   - `avg_risk ≤ RISK_LO (0.45)` and `avg_trend ≥ TREND_BAND (0.2)` → `risk_on`.
   - otherwise → `transition`.

`previous_state` comes from `RunContext`; `changed_this_run = (state != previous_state)`.

**Regime confidence ∈ [0,1] (deterministic):** `0.5·margin + 0.5·concordance`, where
- `margin` = normalized distance of (`avg_risk`,`avg_trend`) from the nearest decision boundary (a read deep
  inside a regime is high-margin; one sitting on a threshold is low-margin), clamped [0,1];
- `concordance` = agreement among the per-asset trend signs (fraction agreeing with `sign(avg_trend)`).

For `event_driven`, `margin` uses the surprise magnitude vs its materiality threshold.

**USD/IRR exception:** `regime_sensitivity: low` assets are excluded from the aggregates and are analyzed on
their own signals; the global regime does not govern them (ADR-005).

## 6. Determinism & clamping
Every function is a pure function of its inputs + config; identical inputs → identical outputs (replay). All
outputs are clamped to contract ranges before return. Constants above (`SCALE_*`, `ATR_FULL`, `RISK_*`, etc.)
are module constants documented here; moving them to config is a future MINOR change, not needed for MVP.
