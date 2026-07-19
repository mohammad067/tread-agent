"""Market State Engine.

A deterministic, explainable, auditable engine producing a Market State — a structured
snapshot of market conditions — across six assets plus a Global Regime.

The deterministic core owns all numbers. The External LLM Provider is reached only through
the frozen ``MarketReasoner`` port. See ``docs/architecture/overview.md``.
"""

__version__ = "0.1.0"
