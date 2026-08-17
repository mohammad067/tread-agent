"""Per-asset deterministic news-relevance tests."""

from __future__ import annotations

import pytest

from market_state_engine.core.dtos import NewsItem
from market_state_engine.news.relevance import (
    compute_asset_relevance,
    compute_relevance,
    compute_relevance_map,
)

TARGETS = {"BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"}


def _item(
    title: str,
    *,
    body: str | None = None,
    tags: list[str] | None = None,
    relevance: float | None = None,
) -> NewsItem:
    return NewsItem(
        news_id="news-1",
        title=title,
        source="test",
        published_at="2026-08-17T00:00:00Z",
        body=body,
        asset_tags=tags,
        relevance=relevance,
    )


def test_xrp_is_broad_crypto_but_not_btc_or_eth() -> None:
    scores = compute_relevance_map(_item("XRP traders expect rebound"), TARGETS)

    assert scores["BTC"] == 0.0
    assert scores["ETH"] == 0.0
    assert scores["TOTAL_MCAP"] > 0.0


def test_bitcoin_direct_match_is_asset_specific() -> None:
    scores = compute_relevance_map(_item("Bitcoin futures market crowded"), TARGETS)

    assert scores["BTC"] > 0.0
    assert scores["ETH"] == 0.0


def test_word_boundaries_prevent_method_matching_eth() -> None:
    scores = compute_relevance_map(_item("New method improves execution"), TARGETS)

    assert scores["ETH"] == 0.0


def test_company_name_bits_of_gold_is_not_metal_relevance() -> None:
    scores = compute_relevance_map(_item("Bits of Gold hit by data breach"), TARGETS)

    assert scores["GOLD"] == 0.0


@pytest.mark.parametrize(
    "headline",
    [
        "Gold prices rise on safe-haven demand",
        "Spot gold hits record high",
        "XAUUSD falls after Fed decision",
    ],
)
def test_gold_market_context_is_directly_relevant(headline: str) -> None:
    scores = compute_relevance_map(_item(headline), TARGETS)

    assert scores["GOLD"] > 0.0


def test_trusted_tag_is_strongest_direct_evidence() -> None:
    scores = compute_relevance_map(_item("General market note", tags=["btc"]), TARGETS)

    assert scores["BTC"] == 1.0
    assert compute_asset_relevance(_item("General note", tags=["BTC"]), "btc") == 1.0


def test_fed_cut_and_hike_have_identical_direction_free_relevance() -> None:
    cut = compute_relevance_map(_item("Fed cuts rates by 25 bps"), TARGETS)
    hike = compute_relevance_map(_item("Fed raises rates by 25 bps"), TARGETS)

    assert cut == hike
    assert all(cut[asset] > 0.0 for asset in TARGETS)


def test_hormuz_is_cross_market_relevant() -> None:
    scores = compute_relevance_map(_item("Tensions rise near the Strait of Hormuz"), TARGETS)

    assert scores["WTI"] > 0.0
    assert scores["GOLD"] > 0.0
    assert scores["USD_IRR"] > 0.0


@pytest.mark.parametrize(
    "headline",
    [
        "Russia jails anti-war politician",
        "Opposition debates a war of attrition in domestic politics",
    ],
)
def test_bare_war_language_does_not_trigger_geopolitical_macro(headline: str) -> None:
    scores = compute_relevance_map(_item(headline), TARGETS)

    assert scores == {asset: 0.0 for asset in sorted(TARGETS)}


@pytest.mark.parametrize(
    "headline",
    [
        "Hormuz shipping disrupted after military escalation",
        "Missile attack raises regional tensions",
        "New sanctions imposed on Iran",
    ],
)
def test_strong_geopolitical_events_trigger_cross_market_relevance(headline: str) -> None:
    scores = compute_relevance_map(_item(headline), TARGETS)

    assert scores["WTI"] > 0.0
    assert scores["GOLD"] > 0.0
    assert scores["USD_IRR"] > 0.0


@pytest.mark.parametrize(
    "headline",
    [
        "Core CPI and PCE remain elevated",
        "NFP report shows a cooling labor market",
        "DXY rises with stronger USD",
        "Treasury yields reach a new high",
        "OPEC announces an oil supply cut",
    ],
)
def test_required_macro_topics_produce_multi_asset_relevance(headline: str) -> None:
    scores = compute_relevance_map(_item(headline), TARGETS)

    assert sum(value > 0.0 for value in scores.values()) > 1


def test_company_us_dollar_reserve_is_not_fx_macro_relevance() -> None:
    scores = compute_relevance_map(
        _item(
            "Strategy raises $334M through stock sales but buys no Bitcoin",
            body=(
                "Proceeds funded STRC dividends and repurchases, while $149.1 million "
                "was added to Strategy's US dollar reserve, which reached $4.8 billion."
            ),
        ),
        TARGETS,
    )

    assert scores == {
        "BTC": 0.75,
        "ETH": 0.0,
        "GOLD": 0.0,
        "TOTAL_MCAP": 0.0,
        "USD_IRR": 0.0,
        "WTI": 0.0,
    }


@pytest.mark.parametrize(
    "headline",
    [
        "US Dollar Index rises to three-month high",
        "DXY falls in currency trading",
        "Stronger dollar pressures gold and oil",
        "Weaker dollar supports risk assets",
    ],
)
def test_market_qualified_us_dollar_language_is_macro_relevant(headline: str) -> None:
    scores = compute_relevance_map(_item(headline), TARGETS)

    assert scores["BTC"] > 0.0
    assert scores["ETH"] > 0.0
    assert scores["GOLD"] > 0.0
    assert scores["WTI"] > 0.0
    assert scores["TOTAL_MCAP"] > 0.0
    assert scores["USD_IRR"] == 0.0


def test_dxy_with_fed_decision_preserves_independent_fed_relevance() -> None:
    scores = compute_relevance_map(_item("DXY falls after Fed decision"), TARGETS)

    assert all(scores[asset] > 0.0 for asset in TARGETS)


def test_dollar_denomination_without_market_movement_is_not_macro_relevant() -> None:
    scores = compute_relevance_map(
        _item("Company increases dollar-denominated cash reserves"), TARGETS
    )

    assert scores == {asset: 0.0 for asset in sorted(TARGETS)}


def test_scalar_upstream_relevance_is_not_broadcast_without_asset_evidence() -> None:
    scores = compute_relevance_map(
        _item("Unclassified company update", relevance=0.9),
        TARGETS,
    )

    assert scores == {asset: 0.0 for asset in sorted(TARGETS)}


def test_scalar_upstream_relevance_only_strengthens_identified_assets() -> None:
    scores = compute_relevance_map(
        _item("Bitcoin update", relevance=0.9),
        TARGETS,
    )

    assert scores["BTC"] == pytest.approx(0.9)
    assert scores["ETH"] == 0.0
    assert scores["GOLD"] == 0.0


def test_legacy_scalar_returns_max_without_changing_asset_map() -> None:
    item = _item("Fed decision after CPI")
    scores = compute_relevance_map(item, TARGETS)

    assert compute_relevance(item, TARGETS) == max(scores.values())
