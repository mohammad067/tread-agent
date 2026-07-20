"""ScoringEngine: compose per-asset scores + MHI + regime into deterministic outputs. Pure.

Given a FeatureSet, config, previous regime, and optional sentiment (None in the deterministic-only
/ degraded path), produces per-asset AssetScores + MHI and the RegimeResult. Regime is computed
first (ADR-005); USD/IRR (regime_sensitivity: low) is excluded from the regime aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_state_engine.config.loader import ConfigBundle
from market_state_engine.core.dtos import AssetScores, FeatureSet, RegimeResult
from market_state_engine.core.enums import AssetClass, RegimeSensitivity, RegimeState

from . import confidence as conf
from . import mhi as mhi_mod
from . import risk as risk_mod
from . import trend as trend_mod
from .regime import AssetRegimeInput, classify

# Expected trend sub-signal counts per class (for the confidence completeness term).
_EXPECTED_SIGNALS = {
    AssetClass.CRYPTO: 5,
    AssetClass.METAL: 5,
    AssetClass.ENERGY: 5,
    AssetClass.FX: 5,
    AssetClass.INDEX: 2,
}


@dataclass(frozen=True)
class ScoredAsset:
    scores: AssetScores
    market_health_index: int


@dataclass(frozen=True)
class ScoringResult:
    per_asset: dict[str, ScoredAsset]
    regime: RegimeResult


class ScoringEngine:
    def __init__(self, config: ConfigBundle) -> None:
        self._config = config

    def score(
        self,
        feature_set: FeatureSet,
        previous_state: RegimeState | None,
        sentiment: dict[str, float] | None = None,
    ) -> ScoringResult:
        per_asset: dict[str, ScoredAsset] = {}
        regime_inputs: list[AssetRegimeInput] = []

        # Risk uses the nearest active event's proximity (same event window for all assets).
        nearest_proximity = self._nearest_event_proximity(feature_set)

        for symbol, cfg in self._config.assets.items():
            features = feature_set.per_asset.get(symbol)
            if features is None:
                continue
            t = trend_mod.trend_score(features)
            r = risk_mod.risk_score(features, nearest_proximity)
            expected = _EXPECTED_SIGNALS[cfg.asset_class]
            c = conf.system_confidence(features, expected)
            s = sentiment.get(symbol) if sentiment is not None else None
            mhi_value = mhi_mod.market_health_index(
                self._config.mhi_weights, t, r, s, features.atr_pct
            )
            per_asset[symbol] = ScoredAsset(
                scores=AssetScores(
                    trend=round(t, 4),
                    risk=round(r, 4),
                    sentiment=(round(s, 4) if s is not None else None),
                    confidence=round(c, 4),
                ),
                market_health_index=mhi_value,
            )
            regime_inputs.append(
                AssetRegimeInput(
                    symbol=symbol,
                    trend=t,
                    risk=r,
                    regime_sensitivity=RegimeSensitivity(cfg.regime_sensitivity.value),
                )
            )

        regime = classify(regime_inputs, feature_set.event_features, previous_state)
        return ScoringResult(per_asset=per_asset, regime=regime)

    def _nearest_event_proximity(self, feature_set: FeatureSet) -> float | None:
        if not feature_set.event_features:
            return None
        return min((e.proximity_hours for e in feature_set.event_features), key=abs)
