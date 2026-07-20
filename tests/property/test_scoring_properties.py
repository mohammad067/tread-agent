"""Property tests: scoring outputs always stay within their contract ranges."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from market_state_engine.config.models import MhiWeights
from market_state_engine.core.dtos import AssetChanges, AssetFeatures
from market_state_engine.scoring import confidence as conf
from market_state_engine.scoring import mhi as mhi_mod
from market_state_engine.scoring import risk as risk_mod
from market_state_engine.scoring import trend as trend_mod

_MACD = ["bullish_cross", "bearish_cross", "neutral", "bullish", "bearish"]
_EMA = [
    "above_diverging",
    "above_converging",
    "below_diverging",
    "below_converging",
    "crossing",
]

floats = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)
pos = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


@given(
    rsi=st.floats(0.0, 100.0),
    macd=st.sampled_from(_MACD),
    ema=st.sampled_from(_EMA),
    h24=floats,
    d7=floats,
)
@pytest.mark.property
def test_trend_always_in_range(rsi: float, macd: str, ema: str, h24: float, d7: float) -> None:
    f = AssetFeatures(
        indicators={"rsi_14": rsi, "macd_state": macd, "ema_20_50": ema},
        changes=AssetChanges.model_validate({"6h": None, "24h": h24, "7d": d7, "30d": None}),
    )
    assert -1.0 <= trend_mod.trend_score(f) <= 1.0


@given(atr=pos, vol=pos, prox=st.one_of(st.none(), floats))
@pytest.mark.property
def test_risk_always_in_range(atr: float, vol: float, prox: float | None) -> None:
    f = AssetFeatures(
        changes=AssetChanges.model_validate({"6h": None, "24h": None, "7d": None, "30d": None}),
        atr_pct=atr,
        volume_ratio_20d=vol,
    )
    assert 0.0 <= risk_mod.risk_score(f, prox) <= 1.0


@given(rsi=st.floats(0.0, 100.0))
@pytest.mark.property
def test_confidence_always_in_range(rsi: float) -> None:
    f = AssetFeatures(
        indicators={"rsi_14": rsi},
        changes=AssetChanges.model_validate({"6h": None, "24h": 1.0, "7d": None, "30d": None}),
    )
    assert 0.0 <= conf.system_confidence(f, 5) <= 1.0


@given(
    trend=st.floats(-1.0, 1.0),
    risk=st.floats(0.0, 1.0),
    sentiment=st.one_of(st.none(), st.floats(-1.0, 1.0)),
    atr=st.one_of(st.none(), pos),
)
@pytest.mark.property
def test_mhi_always_0_100(
    trend: float, risk: float, sentiment: float | None, atr: float | None
) -> None:
    w = MhiWeights(
        version="1.1.0",
        weights={"trend": 0.4, "risk": 0.35, "sentiment": 0.15, "volatility": 0.1},
    )
    v = mhi_mod.market_health_index(w, trend, risk, sentiment, atr)
    assert 0 <= v <= 100
