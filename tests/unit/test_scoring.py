"""Unit tests for trend, risk, confidence, MHI, and regime scoring."""

from __future__ import annotations

from market_state_engine.config.models import MhiWeights
from market_state_engine.core.dtos import AssetChanges, AssetFeatures, EventFeature
from market_state_engine.core.enums import RegimeSensitivity, RegimeState
from market_state_engine.scoring import confidence as conf
from market_state_engine.scoring import mhi as mhi_mod
from market_state_engine.scoring import risk as risk_mod
from market_state_engine.scoring import trend as trend_mod
from market_state_engine.scoring.regime import AssetRegimeInput, classify


def _features(**kw: object) -> AssetFeatures:
    changes = AssetChanges.model_validate(
        {
            "6h": kw.get("h6"),
            "24h": kw.get("h24"),
            "7d": kw.get("d7"),
            "30d": kw.get("d30"),
        }
    )
    return AssetFeatures(
        indicators=kw.get("indicators"),  # type: ignore[arg-type]
        changes=changes,
        atr_pct=kw.get("atr_pct"),  # type: ignore[arg-type]
        volume_ratio_20d=kw.get("vol"),  # type: ignore[arg-type]
    )


def test_trend_bullish_indicators_positive() -> None:
    f = _features(
        indicators={"ema_20_50": "above_diverging", "macd_state": "bullish_cross", "rsi_14": 70.0},
        h24=3.0,
        d7=8.0,
    )
    assert trend_mod.trend_score(f) > 0.5


def test_trend_bearish_indicators_negative() -> None:
    f = _features(
        indicators={"ema_20_50": "below_diverging", "macd_state": "bearish_cross", "rsi_14": 30.0},
        h24=-3.0,
        d7=-8.0,
    )
    assert trend_mod.trend_score(f) < -0.5


def test_trend_no_signal_is_zero() -> None:
    assert trend_mod.trend_score(_features()) == 0.0


def test_trend_bounded() -> None:
    f = _features(
        indicators={"ema_20_50": "above_diverging", "macd_state": "bullish_cross", "rsi_14": 100.0},
        h24=100.0,
        d7=100.0,
    )
    assert -1.0 <= trend_mod.trend_score(f) <= 1.0


def test_risk_high_atr_and_event() -> None:
    f = _features(atr_pct=5.0, vol=3.0)
    assert risk_mod.risk_score(f, event_proximity_hours=0.0) > 0.7


def test_risk_no_signal_is_zero() -> None:
    assert risk_mod.risk_score(_features(), None) == 0.0


def test_risk_bounded() -> None:
    f = _features(atr_pct=100.0, vol=100.0)
    assert 0.0 <= risk_mod.risk_score(f, 0.0) <= 1.0


def test_confidence_more_signals_higher() -> None:
    few = _features(indicators={"rsi_14": 55.0}, h24=1.0)
    many = _features(
        indicators={"ema_20_50": "above_diverging", "macd_state": "bullish", "rsi_14": 60.0},
        h24=2.0,
        d7=3.0,
    )
    assert conf.system_confidence(many, 5) >= conf.system_confidence(few, 5)


def test_confidence_bounded() -> None:
    f = _features(indicators={"rsi_14": 50.0})
    assert 0.0 <= conf.system_confidence(f, 5) <= 1.0


def test_mhi_range_and_direction() -> None:
    w = MhiWeights(
        version="1.1.0",
        weights={"trend": 0.4, "risk": 0.35, "sentiment": 0.15, "volatility": 0.1},
    )
    healthy = mhi_mod.market_health_index(w, trend=0.8, risk=0.1, sentiment=0.5, atr_pct=0.5)
    unhealthy = mhi_mod.market_health_index(w, trend=-0.8, risk=0.9, sentiment=-0.5, atr_pct=4.0)
    assert 0 <= unhealthy < healthy <= 100


def test_mhi_degraded_drops_sentiment() -> None:
    w = MhiWeights(
        version="1.1.0",
        weights={"trend": 0.4, "risk": 0.35, "sentiment": 0.15, "volatility": 0.1},
    )
    # No sentiment (degraded) still yields a valid 0-100 value.
    v = mhi_mod.market_health_index(w, trend=0.2, risk=0.4, sentiment=None, atr_pct=1.0)
    assert 0 <= v <= 100


def _ari(symbol: str, trend: float, risk: float, sens: RegimeSensitivity) -> AssetRegimeInput:
    return AssetRegimeInput(symbol=symbol, trend=trend, risk=risk, regime_sensitivity=sens)


def test_regime_risk_off() -> None:
    assets = [
        _ari("BTC", -0.6, 0.8, RegimeSensitivity.HIGH),
        _ari("ETH", -0.5, 0.75, RegimeSensitivity.HIGH),
    ]
    r = classify(assets, [], previous_state=RegimeState.TRANSITION)
    assert r.state == "risk_off"
    assert r.changed_this_run is True
    assert 0.0 <= r.confidence <= 1.0


def test_regime_risk_on() -> None:
    assets = [
        _ari("BTC", 0.6, 0.3, RegimeSensitivity.HIGH),
        _ari("ETH", 0.5, 0.35, RegimeSensitivity.HIGH),
    ]
    r = classify(assets, [], previous_state=RegimeState.RISK_ON)
    assert r.state == "risk_on"
    assert r.changed_this_run is False


def test_regime_event_driven_on_material_surprise() -> None:
    events = [
        EventFeature(
            event_id="us_cpi_2026_07",
            event_type="us_cpi",
            surprise=0.2,
            surprise_sigma=1.3,
            proximity_hours=1.0,
        )
    ]
    assets = [_ari("BTC", -0.1, 0.5, RegimeSensitivity.HIGH)]
    r = classify(assets, events, previous_state=None)
    assert r.state == "event_driven"


def test_regime_excludes_low_sensitivity_assets() -> None:
    # USD/IRR bullish/low-risk should not pull the regime toward risk_on.
    assets = [
        _ari("BTC", -0.6, 0.8, RegimeSensitivity.HIGH),
        _ari("USD_IRR", 0.9, 0.1, RegimeSensitivity.LOW),
    ]
    r = classify(assets, [], previous_state=None)
    assert r.state == "risk_off"


def test_regime_transition_default() -> None:
    assets = [_ari("BTC", 0.0, 0.5, RegimeSensitivity.HIGH)]
    r = classify(assets, [], previous_state=None)
    assert r.state == "transition"


def test_regime_determinism() -> None:
    assets = [_ari("BTC", -0.6, 0.8, RegimeSensitivity.HIGH)]
    r1 = classify(assets, [], RegimeState.TRANSITION)
    r2 = classify(assets, [], RegimeState.TRANSITION)
    assert r1 == r2
