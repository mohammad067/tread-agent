"""``Router`` — provider ordering by priority or weight (ADR-007 D-5 / §7).

Produces the ordered failover chain the Gateway walks:

  - **priority** (default): providers in ascending ``priority`` (ties by name) — deterministic.
  - **weighted**: the *first* pick is chosen by ``weight`` among the candidates, then the remainder
    follow by priority. The weighted choice is **deterministic per run** — seeded from the run id,
    not a random source — so replay reproduces the exact same routing (frozen invariant #6). Weight
    only selects the first pick; failover still falls through by priority (ADR-011 DR-1).

The Router is pure: it takes the candidate ``ProviderCfg`` list (already filtered to enabled +
breaker-allowed by the Gateway) and returns an ordered list. It touches no scores and does no I/O.
"""

from __future__ import annotations

import hashlib

from ..provider_config import ProviderCfg


def _by_priority(providers: list[ProviderCfg]) -> list[ProviderCfg]:
    return sorted(providers, key=lambda p: (p.priority, p.name))


def _seed_fraction(seed: str) -> float:
    """A stable [0, 1) fraction derived from ``seed`` (deterministic across processes)."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # Use the first 8 bytes as an unsigned integer, scaled to [0, 1).
    value = int.from_bytes(digest[:8], "big")
    return value / 2**64


class Router:
    def __init__(self, strategy: str) -> None:
        self._strategy = strategy

    @property
    def strategy(self) -> str:
        return self._strategy

    def order(self, providers: list[ProviderCfg], seed: str) -> list[ProviderCfg]:
        """Return the ordered failover chain for this run."""
        if not providers:
            return []
        ordered = _by_priority(providers)
        if self._strategy != "weighted":
            return ordered
        return self._weighted_first(ordered, seed)

    def _weighted_first(self, ordered: list[ProviderCfg], seed: str) -> list[ProviderCfg]:
        total = sum(max(0, p.weight) for p in ordered)
        if total <= 0:
            # No usable weights: fall back to pure priority order.
            return ordered
        target = _seed_fraction(seed) * total
        cumulative = 0.0
        first = ordered[0]
        for provider in ordered:
            cumulative += max(0, provider.weight)
            if target < cumulative:
                first = provider
                break
        # First pick chosen by weight; the rest follow by priority (excluding the first).
        rest = [p for p in ordered if p.name != first.name]
        return [first, *rest]
