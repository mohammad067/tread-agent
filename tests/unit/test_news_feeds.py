"""Direct tests for deterministic RSS ingestion boundaries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.core.enums import TriggerType
from market_state_engine.core.run_context import RunContext
from market_state_engine.ingestion.real import news_feeds
from market_state_engine.ingestion.real.news_feeds import (
    RssNewsSource,
    _merge_duplicate,
    _parse_feed,
)
from market_state_engine.news.relevance import compute_relevance_map

_FALLBACK = datetime(2026, 8, 17, 3, 4, 5, tzinfo=timezone.utc)


def _xml(title: str, *, link: str = "https://example.test/article") -> bytes:
    return (
        "<rss><channel><item>"
        f"<title>{title}</title><link>{link}</link>"
        "<description>Article body</description>"
        "</item></channel></rss>"
    ).encode()


def _xml_many(titles: list[str]) -> bytes:
    entries = "".join(
        "<item>"
        f"<title>{title}</title>"
        f"<link>https://example.test/{index}</link>"
        "<description>Article body</description>"
        "</item>"
        for index, title in enumerate(titles)
    )
    return f"<rss><channel>{entries}</channel></rss>".encode()


def _ctx() -> RunContext:
    return RunContext(
        run_id="run-news",
        run_sequence=1,
        trigger_type=TriggerType.SCHEDULED,
        now=_FALLBACK,
        previous_state=None,
        versions={},
    )


def test_configured_feed_defaults_are_trusted_context_only() -> None:
    defaults = [(url, tags) for url, _source, tags in news_feeds._FEEDS]

    assert defaults[0][1] == ["BTC"]
    assert defaults[1][1] == ["ETH"]
    assert defaults[2][1] == ["GOLD"]
    assert defaults[3][1] == []
    assert defaults[4][1] == []
    assert defaults[5][1] == []


def test_general_feed_keeps_untagged_macro_and_asset_text() -> None:
    macro = _parse_feed(_xml("Fed cuts rates by 25 bps"), "coindesk", [], _FALLBACK)
    bitcoin = _parse_feed(_xml("Bitcoin rises"), "coindesk", [], _FALLBACK)

    assert macro[0].asset_tags == []
    assert bitcoin[0].asset_tags == []


def test_default_source_does_not_drop_untagged_candidates_before_relevance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titles = [f"General company update {index}" for index in range(41)]
    titles.append("Oil prices rise on supply concerns")
    monkeypatch.setattr(news_feeds, "_fetch", lambda _url: _xml_many(titles))
    source = RssNewsSource(feeds=[("https://feed.test", "coindesk", [])])

    items = source.fetch_items(_ctx())

    assert len(items) == 42
    oil_item = next(item for item in items if item.title.startswith("Oil prices"))
    assert oil_item.asset_tags == []
    assert compute_relevance_map(oil_item, {"WTI"})["WTI"] > 0.0


def test_specialized_feed_applies_only_its_trusted_default() -> None:
    items = _parse_feed(
        _xml("Ethereum and CPI affect gold"),
        "cointelegraph",
        ["BTC"],
        _FALLBACK,
    )

    assert items[0].asset_tags == ["BTC"]


def test_missing_date_uses_run_context_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_feeds, "_fetch", lambda _url: _xml("Macro update"))
    source = RssNewsSource(feeds=[("https://feed.test", "test", [])])

    items = source.fetch_items(_ctx())

    assert items[0].published_at == "2026-08-17T03:04:05Z"


def test_duplicate_specialized_feeds_merge_trusted_tags() -> None:
    bitcoin = _parse_feed(_xml("Shared article"), "cointelegraph", ["BTC"], _FALLBACK)[0]
    ethereum = _parse_feed(_xml("Shared article"), "cointelegraph", ["ETH"], _FALLBACK)[0]

    assert bitcoin.news_id == ethereum.news_id
    assert _merge_duplicate(bitcoin, ethereum).asset_tags == ["BTC", "ETH"]


@pytest.mark.parametrize(
    ("title", "is_wti_relevant"),
    [
        ("Ferrari charity auction attracts collectors", False),
        ("Earthquake damages buildings near the coast", False),
        ("India jobless rate changes in July", False),
        ("Saudi Aramco increases crude exports", True),
        ("Oil prices rise on supply concerns", True),
    ],
)
def test_reuters_google_news_requires_textual_wti_evidence(
    title: str,
    is_wti_relevant: bool,
) -> None:
    item = _parse_feed(
        _xml(title),
        "reuters_via_gn",
        [],
        _FALLBACK,
    )[0]

    assert item.asset_tags == []
    score = compute_relevance_map(item, {"WTI"})["WTI"]
    assert (score > 0.0) is is_wti_relevant
