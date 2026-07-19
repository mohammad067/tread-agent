"""Ubiquitous-language enumerations. Values are the exact tokens used in the frozen contracts."""

from __future__ import annotations

from enum import Enum


class RegimeState(str, Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    TRANSITION = "transition"
    EVENT_DRIVEN = "event_driven"


class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    EVENT = "event"


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    METAL = "metal"
    ENERGY = "energy"
    FX = "fx"
    INDEX = "index"


class RegimeSensitivity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WeightType(str, Enum):
    COMPUTED = "computed"
    ORDINAL = "ordinal"


class OrdinalLevel(str, Enum):
    DOMINANT = "dominant"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MacdState(str, Enum):
    BULLISH_CROSS = "bullish_cross"
    BEARISH_CROSS = "bearish_cross"
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


class EmaState(str, Enum):
    ABOVE_DIVERGING = "above_diverging"
    ABOVE_CONVERGING = "above_converging"
    BELOW_DIVERGING = "below_diverging"
    BELOW_CONVERGING = "below_converging"
    CROSSING = "crossing"


class Currency(str, Enum):
    USD = "USD"
    IRT = "IRT"


class FearGreedLabel(str, Enum):
    EXTREME_FEAR = "extreme_fear"
    FEAR = "fear"
    NEUTRAL = "neutral"
    GREED = "greed"
    EXTREME_GREED = "extreme_greed"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EventType(str, Enum):
    US_CPI = "us_cpi"
    FOMC = "fomc"
    US_NFP = "us_nfp"


class LlmJob(str, Enum):
    SENTIMENT = "sentiment"
    SYNTHESIS = "synthesis"
