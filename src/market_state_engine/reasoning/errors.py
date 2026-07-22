"""Reasoning-layer error taxonomy. Distinct from the deterministic-core errors."""

from __future__ import annotations


class ReasoningError(Exception):
    """Base class for all reasoning-layer errors."""


class ProviderConfigError(ReasoningError):
    """Malformed or missing ``providers.yaml``; fails fast at load, never mid-run."""


class PromptTemplateError(ReasoningError):
    """A prompt template is missing or unreadable."""


class StructuredOutputError(ReasoningError):
    """A provider response failed structured-output validation against the frozen schema.

    Per ADR-011/M1 §4 this is treated as a call failure (never a fabricated result); the
    failover/degraded handling that consumes it arrives in M4.2.
    """


class ProviderCallError(ReasoningError):
    """A provider adapter failed to produce a result on a single attempt."""


class ProviderTimeoutError(ProviderCallError):
    """A provider attempt exceeded its per-provider deadline (a call failure → next provider)."""


class CircuitOpenError(ProviderCallError):
    """A provider was skipped because its circuit breaker is open (not retried until half-open)."""
