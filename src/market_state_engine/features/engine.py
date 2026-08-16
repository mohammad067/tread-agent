"""FeatureEngine: compose all deterministic features into a FeatureSet.

Pure function of (snapshots, config, run context). No I/O, no clock — time comes from ``ctx.now``.
Missing/insufficient inputs produce ``None`` values recorded as data gaps, never exceptions that
abort the run (degrade-not-fail). Byte-reproducible for replay.
"""

from __future__ import annotations

from typing import Any

from market_state_engine.config.loader import ConfigBundle
from market_state_engine.core.dtos import (
    AssetChanges,
    AssetFeatures,
    EventFeature,
    FeatureSet,
    MacroEvent,
    RawSnapshot,
)
from market_state_engine.core.enums import AssetClass
from market_state_engine.core.run_context import RunContext

from . import changes as changes_mod
from . import indicators as ind
from . import surprise as surprise_mod

# Bar cadence for horizon changes: the mock/real series are 6h bars, so:
_HORIZON_BARS = {"6h": 1, "24h": 4, "7d": 28, "30d": 120}


def _floats(raw: object) -> list[float]:
    """Coerce a raw payload sequence into a list of floats; empty if absent/not a sequence."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [float(x) for x in raw]


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class FeatureEngine:
    def __init__(self, config: ConfigBundle) -> None:
        self._config = config

    def compute(
        self,
        price_snapshots: dict[str, RawSnapshot],
        indicator_snapshots: dict[str, RawSnapshot],
        global_snapshots: dict[str, RawSnapshot],
        events: list[MacroEvent],
        ctx: RunContext,
    ) -> FeatureSet:
        per_asset: dict[str, AssetFeatures] = {}
        for symbol, asset_cfg in self._config.assets.items():
            per_asset[symbol] = self._asset_features(
                symbol,
                asset_cfg.asset_class,
                indicator_snapshots.get(symbol),
            )

        event_features: list[EventFeature] = []
        for ev in events:
            ef = surprise_mod.event_feature(ev, ctx.now)
            if ef is not None:
                event_features.append(ef)

        global_features = self._global_features(global_snapshots)
        config_versions: dict[str, object] = dict(self._config.versions)

        return FeatureSet(
            run_id=ctx.run_id,
            per_asset=per_asset,
            global_features=global_features,
            event_features=event_features,
            news_features={},  # populated by the NewsWeigher batch (M3.8)
            config_versions=config_versions,
        )

    def _asset_features(
        self,
        symbol: str,
        asset_class: AssetClass,
        snapshot: RawSnapshot | None,
    ) -> AssetFeatures:
        if snapshot is None:
            return AssetFeatures(
                changes=AssetChanges.model_validate(
                    {"6h": None, "24h": None, "7d": None, "30d": None}
                )
            )
        payload = snapshot.payload
        closes = _floats(payload.get("closes"))
        highs = _floats(payload.get("highs"))
        lows = _floats(payload.get("lows"))
        volumes = _floats(payload.get("volumes"))

        explicit_changes = payload.get("horizon_changes")
        if isinstance(explicit_changes, dict):
            change_values = {
                horizon: _optional_float(explicit_changes.get(horizon))
                for horizon in _HORIZON_BARS
            }
        else:
            change_values = {
                horizon: changes_mod.horizon_change(closes, bars)
                for horizon, bars in _HORIZON_BARS.items()
            }
        asset_changes = AssetChanges.model_validate(change_values)

        indicators = self._indicators(asset_class, closes, highs, lows, volumes)
        atr = indicators.get("atr_pct") if isinstance(indicators.get("atr_pct"), float) else None

        return AssetFeatures(
            indicators=indicators,
            changes=asset_changes,
            atr_pct=atr,
            volume_ratio_20d=(
                indicators.get("volume_ratio_20d")
                if isinstance(indicators.get("volume_ratio_20d"), float)
                else None
            ),
        )

    def _indicators(
        self,
        asset_class: AssetClass,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        # Index assets use the reduced set (A8): atr% only (trend_state/dominance added later).
        try:
            if highs and lows and len(closes) >= 15:
                out["atr_pct"] = ind.atr_pct(highs, lows, closes)
        except ValueError:
            pass
        if asset_class is AssetClass.INDEX:
            return out
        try:
            if len(closes) >= 15:
                out["rsi_14"] = ind.rsi_14(closes)
        except ValueError:
            pass
        try:
            if len(closes) >= 35:
                out["macd_state"] = ind.macd_state(closes).value
        except ValueError:
            pass
        try:
            if len(closes) >= 51:
                out["ema_20_50"] = ind.ema_20_50(closes).value
        except ValueError:
            pass
        try:
            if len(volumes) >= 21:
                out["volume_ratio_20d"] = ind.volume_ratio_20d(volumes)
        except ValueError:
            pass
        return out

    def _global_features(self, global_snapshots: dict[str, RawSnapshot]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        fg = global_snapshots.get("fear_greed")
        if fg is not None:
            out["fear_greed_value"] = fg.payload.get("value")
        dom = global_snapshots.get("dominance")
        if dom is not None:
            out["btc_dominance"] = dom.payload.get("btc_dominance")
        mcap = global_snapshots.get("total_mcap")
        if mcap is not None:
            out["total_market_cap_usd"] = mcap.payload.get("total_market_cap_usd")
        return out
