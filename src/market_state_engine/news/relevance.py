"""Deterministic per-asset news relevance.

This module determines HOW RELEVANT a news item is to each tracked asset.

It does not determine whether the news is bullish or bearish.

Relevance sources:
1. Explicit asset tags supplied by trusted ingestion feeds.
2. Direct textual references to tracked assets.
3. Macro / cross-market topics such as:
   - Federal Reserve / FOMC / interest rates
   - CPI / inflation
   - US dollar / DXY
   - Treasury yields
   - employment / NFP
   - geopolitical risk
   - OPEC / oil supply

The final relevance for an asset is the strongest applicable relevance signal:

    final_relevance[asset] = max(
        explicit_tag_relevance,
        direct_text_relevance,
        macro_relevance,
    )

Sentiment direction is intentionally NOT handled here.

For example:

    "Fed cuts rates by 25 bps"

may be highly relevant to GOLD, BTC and TOTAL_MCAP, but whether that is
bullish or bearish belongs to the sentiment/reasoning layer.

The deprecated scalar ``compute_relevance()`` compatibility shim is retained
temporarily. New multi-asset code must use ``compute_relevance_map()``.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass

from market_state_engine.core.dtos import NewsItem

# ---------------------------------------------------------------------------
# Relevance constants
# ---------------------------------------------------------------------------

_DIRECT_TAG_RELEVANCE = 1.0
_DIRECT_TEXT_RELEVANCE = 0.75
_EVIDENCE_TEXT_LIMIT = 2000


# ---------------------------------------------------------------------------
# Direct asset patterns
# ---------------------------------------------------------------------------
#
# These patterns mean that the article explicitly talks about the asset or
# about a directly associated market instrument.
#
# Cross-market macro relationships must NOT be added here.
#

_DIRECT_ASSET_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "BTC": (
        re.compile(r"\bbitcoin\b", re.IGNORECASE),
        re.compile(r"\bbtc\b", re.IGNORECASE),
        re.compile(r"\bsatoshi(?:s)?\b", re.IGNORECASE),
    ),
    "ETH": (
        re.compile(r"\bethereum\b", re.IGNORECASE),
        re.compile(r"\beth\b", re.IGNORECASE),
        re.compile(r"\bether\b", re.IGNORECASE),
        re.compile(r"\bvitalik\b", re.IGNORECASE),
    ),
    "GOLD": (
        re.compile(r"\bgold\s+price(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bspot\s+gold\b", re.IGNORECASE),
        re.compile(r"\bgold\s+futures?\b", re.IGNORECASE),
        re.compile(r"\bgold\s+market\b", re.IGNORECASE),
        re.compile(r"\bxau(?:usd)?\b", re.IGNORECASE),
        re.compile(r"\bbullion\b", re.IGNORECASE),
        re.compile(
            r"\bgold\s+(?:rises?|rose|falls?|fell|gains?|gained|drops?|dropped|"
            r"rall(?:y|ies|ied)|slips?|slid|surges?|jumped|climbs?|declines?)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bgold(?:'s)?\s+safe[- ]haven\b", re.IGNORECASE),
        re.compile(r"\bgold\s+(?:demand|supply)\b", re.IGNORECASE),
        re.compile(
            r"\bprecious\s+metals?\s+(?:market|price(?:s)?|demand|supply)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:demand|supply|price(?:s)?)\s+(?:for|of)\s+precious\s+metals?\b",
            re.IGNORECASE,
        ),
    ),
    "WTI": (
        re.compile(r"\bwti\b", re.IGNORECASE),
        re.compile(r"\bwest\s+texas\s+intermediate\b", re.IGNORECASE),
        re.compile(r"\bcrude(?:\s+oil)?\b", re.IGNORECASE),
        re.compile(r"\boil\s+price(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bbrent\b", re.IGNORECASE),
        re.compile(r"\bopec\+?\b", re.IGNORECASE),
        re.compile(r"\bpetroleum\b", re.IGNORECASE),
    ),
    "USD_IRR": (
        re.compile(r"\biranian\s+rial\b", re.IGNORECASE),
        re.compile(r"\biran(?:'s)?\s+rial\b", re.IGNORECASE),
        re.compile(r"\brial\b", re.IGNORECASE),
        re.compile(r"\btoman\b", re.IGNORECASE),
        re.compile(r"\busd\s*[/_-]?\s*irr\b", re.IGNORECASE),
        re.compile(r"\bdollar\s+(?:rate|price)\s+in\s+iran\b", re.IGNORECASE),
    ),
    "TOTAL_MCAP": (
        re.compile(r"\bcrypto\s+market\b", re.IGNORECASE),
        re.compile(r"\bcryptocurrency\s+market\b", re.IGNORECASE),
        re.compile(r"\bcrypto\b", re.IGNORECASE),
        re.compile(r"\bcryptocurrenc(?:y|ies)\b", re.IGNORECASE),
        re.compile(r"\bdigital\s+assets?\b", re.IGNORECASE),
        re.compile(r"\bcrypto\s+market\s+cap(?:italization)?\b", re.IGNORECASE),
        re.compile(r"\btotal\s+crypto\s+market\s+cap\b", re.IGNORECASE),
        re.compile(r"\baltcoin(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bstablecoin(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bxrp\b", re.IGNORECASE),
        re.compile(r"\bsolana\b", re.IGNORECASE),
    ),
}


# ---------------------------------------------------------------------------
# Macro / cross-market topics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroTopic:
    """One deterministic macro-news relevance rule.

    ``asset_relevance`` represents importance/relevance only.

    It does NOT represent:
    - bullishness,
    - bearishness,
    - expected return,
    - price direction.
    """

    patterns: tuple[re.Pattern[str], ...]
    asset_relevance: dict[str, float]


_MACRO_TOPICS: dict[str, MacroTopic] = {
    # Federal Reserve, FOMC and interest-rate decisions are globally relevant
    # to risk assets, gold, USD-sensitive markets and commodities.
    "FED_MONETARY_POLICY": MacroTopic(
        patterns=(
            re.compile(r"\bfederal\s+reserve\b", re.IGNORECASE),
            re.compile(r"\bthe\s+fed\b", re.IGNORECASE),
            re.compile(r"\bfed\b", re.IGNORECASE),
            re.compile(r"\bfomc\b", re.IGNORECASE),
            re.compile(r"\bpowell\b", re.IGNORECASE),
            re.compile(r"\bjerome\s+powell\b", re.IGNORECASE),
            re.compile(r"\bfed\s+funds?\s+rate\b", re.IGNORECASE),
            re.compile(r"\binterest\s+rate(?:s)?\b", re.IGNORECASE),
            re.compile(r"\brate\s+cut(?:s)?\b", re.IGNORECASE),
            re.compile(r"\brate\s+hike(?:s)?\b", re.IGNORECASE),
            re.compile(r"\brate\s+decision\b", re.IGNORECASE),
            re.compile(r"\bmonetary\s+policy\b", re.IGNORECASE),
        ),
        asset_relevance={
            "BTC": 0.80,
            "ETH": 0.80,
            "GOLD": 0.95,
            "WTI": 0.60,
            "USD_IRR": 0.75,
            "TOTAL_MCAP": 0.90,
        },
    ),
    # Inflation affects rate expectations, real yields and global liquidity.
    "US_INFLATION": MacroTopic(
        patterns=(
            re.compile(r"\bcpi\b", re.IGNORECASE),
            re.compile(r"\bconsumer\s+price\s+index\b", re.IGNORECASE),
            re.compile(r"\bcore\s+cpi\b", re.IGNORECASE),
            re.compile(r"\binflation\b", re.IGNORECASE),
            re.compile(r"\bdisinflation\b", re.IGNORECASE),
            re.compile(r"\bpce\b", re.IGNORECASE),
            re.compile(
                r"\bpersonal\s+consumption\s+expenditures\b",
                re.IGNORECASE,
            ),
        ),
        asset_relevance={
            "BTC": 0.75,
            "ETH": 0.75,
            "GOLD": 0.90,
            "WTI": 0.55,
            "USD_IRR": 0.70,
            "TOTAL_MCAP": 0.85,
        },
    ),
    # US labour-market data influences monetary-policy expectations.
    "US_LABOR_MARKET": MacroTopic(
        patterns=(
            re.compile(r"\bnonfarm\s+payrolls?\b", re.IGNORECASE),
            re.compile(r"\bnfp\b", re.IGNORECASE),
            re.compile(r"\bunemployment\b", re.IGNORECASE),
            re.compile(r"\bjobless\s+claims?\b", re.IGNORECASE),
            re.compile(r"\bpayrolls?\b", re.IGNORECASE),
            re.compile(r"\blabor\s+market\b", re.IGNORECASE),
            re.compile(r"\blabour\s+market\b", re.IGNORECASE),
        ),
        asset_relevance={
            "BTC": 0.65,
            "ETH": 0.65,
            "GOLD": 0.80,
            "WTI": 0.45,
            "USD_IRR": 0.60,
            "TOTAL_MCAP": 0.75,
        },
    ),
    # Dollar strength is an important cross-market driver.
    "US_DOLLAR": MacroTopic(
        patterns=(
            re.compile(r"\bdollar\s+index\b", re.IGNORECASE),
            re.compile(r"\bus\s+dollar\s+index\b", re.IGNORECASE),
            re.compile(r"\bdxy\b", re.IGNORECASE),
            re.compile(r"\busd\s+(?:strength|weakness)\b", re.IGNORECASE),
            re.compile(r"\bstronger\s+usd\b", re.IGNORECASE),
            re.compile(r"\bweaker\s+usd\b", re.IGNORECASE),
            re.compile(r"\bdollar\s+strength\b", re.IGNORECASE),
            re.compile(r"\bdollar\s+weakness\b", re.IGNORECASE),
            re.compile(r"\bstronger\s+dollar\b", re.IGNORECASE),
            re.compile(r"\bweaker\s+dollar\b", re.IGNORECASE),
            re.compile(
                r"\bdollar\s+(?:strengthens?|strengthened|weakens?|weakened|"
                r"rises?|rose|falls?|fell|gains?|gained|slides?|slid)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bdollar\s+rall(?:y|ies|ied)\b", re.IGNORECASE),
            re.compile(r"\bdollar\s+sell[- ]?off\b", re.IGNORECASE),
            re.compile(
                r"\bdollar\s+hits?\s+(?:(?:a|an|new|three-month)\s+)*"
                r"(?:high|low)\b",
                re.IGNORECASE,
            ),
        ),
        asset_relevance={
            "BTC": 0.65,
            "ETH": 0.65,
            "GOLD": 0.90,
            "WTI": 0.70,
            "TOTAL_MCAP": 0.70,
        },
    ),
    # Treasury yields / real yields are especially important for gold and
    # liquidity-sensitive assets.
    "US_YIELDS": MacroTopic(
        patterns=(
            re.compile(r"\btreasury\s+yield(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bus\s+yield(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bbond\s+yield(?:s)?\b", re.IGNORECASE),
            re.compile(r"\breal\s+yield(?:s)?\b", re.IGNORECASE),
            re.compile(r"\b10[- ]year\s+yield\b", re.IGNORECASE),
            re.compile(r"\btwo[- ]year\s+yield\b", re.IGNORECASE),
            re.compile(r"\b2[- ]year\s+yield\b", re.IGNORECASE),
        ),
        asset_relevance={
            "BTC": 0.65,
            "ETH": 0.65,
            "GOLD": 0.95,
            "WTI": 0.45,
            "USD_IRR": 0.65,
            "TOTAL_MCAP": 0.70,
        },
    ),
    # Oil supply policy is directly important for WTI and can have broader
    # inflation / FX implications.
    "OIL_SUPPLY": MacroTopic(
        patterns=(
            re.compile(r"\bopec\+?\b", re.IGNORECASE),
            re.compile(r"\boil\s+production\b", re.IGNORECASE),
            re.compile(r"\bproduction\s+cut(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bproduction\s+increase(?:s)?\b", re.IGNORECASE),
            re.compile(r"\boil\s+supply\b", re.IGNORECASE),
            re.compile(r"\bcrude\s+supply\b", re.IGNORECASE),
        ),
        asset_relevance={
            "BTC": 0.20,
            "ETH": 0.20,
            "GOLD": 0.35,
            "WTI": 0.95,
            "USD_IRR": 0.45,
            "TOTAL_MCAP": 0.25,
        },
    ),
    # Geopolitical events can simultaneously affect energy, safe havens,
    # currencies and risk assets.
    #
    # This is deliberately broad relevance only; sentiment direction remains
    # the responsibility of the reasoning layer.
    "GEOPOLITICAL_RISK": MacroTopic(
        patterns=(
            re.compile(r"\bgeopolitical\s+risk\b", re.IGNORECASE),
            re.compile(r"\bgeopolitical\s+tension(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bmilitary\s+conflict\b", re.IGNORECASE),
            re.compile(r"\barmed\s+conflict\b", re.IGNORECASE),
            re.compile(r"\binvasion\b", re.IGNORECASE),
            re.compile(r"\bmissile\s+attack(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bair\s*strike(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bbombing(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bceasefire\b", re.IGNORECASE),
            re.compile(r"\bmilitary\s+escalation\b", re.IGNORECASE),
            re.compile(r"\bmilitary\s+attack(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bsanction(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bstrait\s+of\s+hormuz\b", re.IGNORECASE),
            re.compile(r"\bhormuz\b", re.IGNORECASE),
            re.compile(r"\bshipping\s+disruption(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bshipping\s+(?:is\s+)?disrupted\b", re.IGNORECASE),
            re.compile(r"\biran[- ](?:us|israel)\s+conflict\b", re.IGNORECASE),
        ),
        asset_relevance={
            "BTC": 0.45,
            "ETH": 0.40,
            "GOLD": 0.90,
            "WTI": 0.90,
            "USD_IRR": 0.90,
            "TOTAL_MCAP": 0.45,
        },
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float) -> float:
    """Clamp a relevance value into the contract range [0.0, 1.0]."""

    return max(0.0, min(1.0, float(value)))


def _normalize_assets(assets: Iterable[str]) -> set[str]:
    """Normalize asset identifiers."""

    return {asset.strip().upper() for asset in assets if asset and asset.strip()}


def build_evidence_text(item: NewsItem) -> str:
    """Return the bounded plain-text body shared by relevance and the LLM."""

    body = item.body or ""
    without_tags = re.sub(r"<[^>]+>", " ", body)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    return normalized[:_EVIDENCE_TEXT_LIMIT]


def _article_text(item: NewsItem) -> str:
    """Build the exact deterministic text surface used for matching."""

    return f"{item.title}\n{build_evidence_text(item)}"


def _match_direct_assets(
    text: str,
    target_assets: set[str],
) -> set[str]:
    """Return assets explicitly/directly mentioned by article text."""

    matched: set[str] = set()

    for asset, patterns in _DIRECT_ASSET_PATTERNS.items():
        if asset not in target_assets:
            continue

        if any(pattern.search(text) for pattern in patterns):
            matched.add(asset)

    return matched


def _compute_macro_relevance(
    text: str,
    target_assets: set[str],
) -> dict[str, float]:
    """Compute relevance caused by deterministic macro-topic matches."""

    scores: dict[str, float] = {asset: 0.0 for asset in target_assets}

    for topic in _MACRO_TOPICS.values():
        if not any(pattern.search(text) for pattern in topic.patterns):
            continue

        for asset, relevance in topic.asset_relevance.items():
            if asset not in target_assets:
                continue

            scores[asset] = max(
                scores[asset],
                _clamp(relevance),
            )

    return scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_relevance_map(
    item: NewsItem,
    target_assets: set[str],
) -> dict[str, float]:
    """Compute deterministic relevance independently for every target asset.

    Relevance precedence for each asset:

        explicit trusted tag
            -> 1.0

        direct text match
            -> 0.75

        macro topic
            -> topic-specific relevance

    Multiple signals are combined with ``max`` instead of addition so that
    overlapping keyword matches cannot artificially push relevance above 1.0.

    Example:

        title:
            "Fed cuts rates as Bitcoin rises"

        possible output:

            {
                "BTC": 0.80,
                "ETH": 0.80,
                "GOLD": 0.95,
                "WTI": 0.60,
                "USD_IRR": 0.75,
                "TOTAL_MCAP": 0.90,
            }

    BTC is directly mentioned, but the Fed macro relevance for BTC (0.80) is
    stronger than the generic direct-text fallback (0.75).

    If BTC was supplied as an explicit trusted feed tag, BTC would be 1.0.
    """

    targets = _normalize_assets(target_assets)

    scores: dict[str, float] = {asset: 0.0 for asset in sorted(targets)}

    if not targets:
        return scores

    text = _article_text(item)

    # ------------------------------------------------------------------
    # Explicit feed/upstream asset tags
    # ------------------------------------------------------------------

    explicit_tags = _normalize_assets(item.asset_tags or [])
    tagged_assets = explicit_tags & targets

    for asset in tagged_assets:
        scores[asset] = _DIRECT_TAG_RELEVANCE

    # ------------------------------------------------------------------
    # Direct textual relevance
    # ------------------------------------------------------------------

    direct_assets = _match_direct_assets(
        text=text,
        target_assets=targets,
    )

    for asset in direct_assets:
        scores[asset] = max(
            scores[asset],
            _DIRECT_TEXT_RELEVANCE,
        )

    # ------------------------------------------------------------------
    # Macro / cross-market relevance
    # ------------------------------------------------------------------

    macro_scores = _compute_macro_relevance(
        text=text,
        target_assets=targets,
    )

    for asset, relevance in macro_scores.items():
        scores[asset] = max(
            scores[asset],
            relevance,
        )

    # ------------------------------------------------------------------
    # Optional upstream relevance
    # ------------------------------------------------------------------
    #
    # ``NewsItem.relevance`` is scalar, so it does not identify WHICH asset
    # the score belongs to.
    #
    # Therefore it must never be broadcast blindly to all target assets.
    #
    # It is applied only to assets that have already been identified through:
    # - explicit tags,
    # - direct text,
    # - macro matching.
    #

    if item.relevance is not None:
        upstream = _clamp(item.relevance)

        identified_assets = {asset for asset, relevance in scores.items() if relevance > 0.0}

        for asset in identified_assets:
            scores[asset] = max(
                scores[asset],
                upstream,
            )

    return scores


def compute_asset_relevance(
    item: NewsItem,
    asset: str,
) -> float:
    """Compute relevance for exactly one tracked asset."""

    normalized = asset.strip().upper()

    if not normalized:
        return 0.0

    return compute_relevance_map(
        item=item,
        target_assets={normalized},
    ).get(normalized, 0.0)


def compute_relevance(
    item: NewsItem,
    target_assets: set[str],
) -> float:
    """Deprecated compatibility shim returning the maximum asset relevance.

    Multi-asset callers must use ``compute_relevance_map()``. This scalar API
    loses asset identity and should be removed in a future compatible cleanup
    once no call sites remain.
    """

    relevance_map = compute_relevance_map(
        item=item,
        target_assets=target_assets,
    )

    return max(
        relevance_map.values(),
        default=0.0,
    )
