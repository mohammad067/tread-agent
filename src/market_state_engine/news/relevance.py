"""Deterministic news relevance (OQ-6).

If the upstream feed provides a trusted relevance score, use it. Otherwise compute relevance
deterministically from asset tags / keyword mappings:
  - explicit asset_tags matching a target asset       -> 1.0
  - keyword hit mapping to a target asset             -> 0.5
  - no match                                          -> 0.0
The maximum across the target asset set is the item's relevance for this run.
"""

from __future__ import annotations

from market_state_engine.core.dtos import NewsItem

# Minimal keyword -> asset map (extensible via config later; MVP is a documented in-code list).
_KEYWORD_ASSETS: dict[str, str] = {
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "eth": "ETH",
    "gold": "GOLD",
    "crude": "WTI",
    "oil": "WTI",
    "wti": "WTI",
    "rial": "USD_IRR",
    "toman": "USD_IRR",
    "tehran": "USD_IRR",
    "crypto": "TOTAL_MCAP",
    "market cap": "TOTAL_MCAP",
    "cpi": "TOTAL_MCAP",
    "inflation": "TOTAL_MCAP",
    "fed": "TOTAL_MCAP",
}


def compute_relevance(item: NewsItem, target_assets: set[str]) -> float:
    if item.relevance is not None:
        return max(0.0, min(1.0, item.relevance))

    best = 0.0
    tags = {t.upper() for t in (item.asset_tags or [])}
    if tags & target_assets:
        best = 1.0
    if best < 1.0:
        text = f"{item.title} {item.body or ''}".lower()
        for keyword, asset in _KEYWORD_ASSETS.items():
            if asset in target_assets and keyword in text:
                best = max(best, 0.5)
    return best
