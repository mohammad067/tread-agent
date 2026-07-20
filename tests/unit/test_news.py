"""News relevance (OQ-6) and weigher (F-6) tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.config.models import HalfLives, SourceQuality
from market_state_engine.core.dtos import NewsItem
from market_state_engine.news.relevance import compute_relevance
from market_state_engine.news.weigher import NewsWeigher

TARGETS = {"BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"}


def test_relevance_uses_trusted_upstream_score() -> None:
    item = NewsItem(
        news_id="n1",
        title="unrelated",
        source="wire_reuters",
        published_at="2026-07-14T12:00:00Z",
        relevance=0.87,
    )
    assert compute_relevance(item, TARGETS) == pytest.approx(0.87)


def test_relevance_from_asset_tags() -> None:
    item = NewsItem(
        news_id="n2",
        title="market note",
        source="wire_reuters",
        published_at="2026-07-14T12:00:00Z",
        asset_tags=["BTC"],
    )
    assert compute_relevance(item, TARGETS) == 1.0


def test_relevance_from_keyword() -> None:
    item = NewsItem(
        news_id="n3",
        title="Bitcoin slips after data",
        source="crypto_media",
        published_at="2026-07-14T12:00:00Z",
    )
    assert compute_relevance(item, TARGETS) == 0.5


def test_relevance_no_match_is_zero() -> None:
    item = NewsItem(
        news_id="n4",
        title="weather forecast",
        source="crypto_media",
        published_at="2026-07-14T12:00:00Z",
    )
    assert compute_relevance(item, TARGETS) == 0.0


def _weigher() -> NewsWeigher:
    sq = SourceQuality(version="1.0.0", sources={"wire_reuters": 0.95}, default_quality=0.5)
    hl = HalfLives(
        version="1.0.0",
        news_half_life_hours={"us_cpi": 24.0, "default": 12.0},
        rule_half_life_defaults={"default": 12.0},
    )
    return NewsWeigher(sq, hl)


def test_effective_weight_is_product() -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)  # 24h after publish
    item = NewsItem(
        news_id="n1",
        title="Bitcoin CPI reaction",
        source="wire_reuters",
        published_at="2026-07-14T12:00:00Z",
        asset_tags=["BTC"],
    )
    digest = _weigher().weigh("run1", [item], TARGETS, now, default_event_type="us_cpi")
    w = digest.items[0]
    # quality 0.95 x relevance 1.0 x decay(24h, hl 24h)=0.5 = 0.475
    assert w.effective_weight == pytest.approx(
        w.source_quality * w.relevance * w.recency_decay, abs=1e-9
    )
    assert w.recency_decay == pytest.approx(0.5, abs=1e-6)


def test_digest_ranked_by_effective_weight() -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            news_id="low",
            title="weather",
            source="crypto_media",
            published_at="2026-07-14T12:00:00Z",
        ),
        NewsItem(
            news_id="high",
            title="Bitcoin surges",
            source="wire_reuters",
            published_at="2026-07-14T12:30:00Z",
            asset_tags=["BTC"],
        ),
    ]
    digest = _weigher().weigh("run1", items, TARGETS, now)
    assert digest.items[0].news_id == "high"
    assert digest.items[0].effective_weight >= digest.items[1].effective_weight


def test_digest_validates_against_schema(make_validator: object) -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    item = NewsItem(
        news_id="n1",
        title="Bitcoin note",
        source="wire_reuters",
        published_at="2026-07-14T12:00:00Z",
        asset_tags=["BTC"],
    )
    digest = _weigher().weigh("run1", [item], TARGETS, now)
    validator = make_validator("news_digest.v1.json")  # type: ignore[operator]
    errors = list(validator.iter_errors(digest.to_contract_dict()))
    assert not errors
