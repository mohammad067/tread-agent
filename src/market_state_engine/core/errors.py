"""Domain error taxonomy. Pure — no I/O, no framework."""

from __future__ import annotations


class MarketStateEngineError(Exception):
    """Base class for all domain errors."""


class ConfigError(MarketStateEngineError):
    """Malformed or missing configuration; must fail fast at load, never mid-run."""


class DataGapError(MarketStateEngineError):
    """A required input is missing; the pipeline degrades and records a data gap, not this raise
    unless a gap cannot even be recorded."""


class StaleDataError(MarketStateEngineError):
    """Data is older than allowed and no last-good value exists to fall back to."""


class RuleGateError(MarketStateEngineError):
    """A rule failed the hard sign-off gate (ADR-008) or a load-time lint."""


class FeatureComputationError(MarketStateEngineError):
    """A deterministic feature could not be computed from the given inputs."""
