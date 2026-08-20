"""News relevance (OQ-6) and weigher (F-6) tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_state_engine.config.models import HalfLives, SourceQuality
from market_state_engine.core.dtos import NewsItem
from market_state_engine.news.weigher import NewsWeigher

TARGETS = {"BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"}


def _weigher() -> NewsWeigher:
    sq = SourceQuality(version="1.0.0", sources={"wire_reuters": 0.95}, default_quality=0.5)
    hl = HalfLives(
        version="1.1.0",
        news_half_life_hours={"us_cpi": 24.0, "default": 12.0},
        rule_half_life_defaults={"default": 12.0},
        max_news_age_hours=36.0,
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
    btc = w.asset_weights["BTC"]
    # quality 0.95 x relevance 1.0 x decay(24h, hl 24h)=0.5 = 0.475
    assert btc.effective_weight == w.source_quality * btc.relevance * w.recency_decay
    assert w.recency_decay == pytest.approx(0.5, abs=1e-6)
    assert w.max_effective_weight == max(
        weight.effective_weight for weight in w.asset_weights.values()
    )
    for weight in w.asset_weights.values():
        assert weight.effective_weight == (w.source_quality * weight.relevance * w.recency_decay)


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
    assert len(digest.items) == 1  # unrelated zero-relevance news is omitted


def test_equal_weights_use_news_id_as_deterministic_tie_break() -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            news_id=news_id,
            title="Bitcoin update",
            source="wire_reuters",
            published_at="2026-07-14T12:00:00Z",
            asset_tags=["BTC"],
        )
        for news_id in ("z-news", "a-news")
    ]

    digest = _weigher().weigh("run1", items, TARGETS, now)

    assert [item.news_id for item in digest.items] == ["a-news", "z-news"]


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
    serialized = digest.to_contract_dict()
    validator = make_validator("news_digest.v3.json")  # type: ignore[operator]
    errors = list(validator.iter_errors(serialized))
    assert not errors
    serialized_item = serialized["items"][0]  # type: ignore[index]
    assert "asset_weights" in serialized_item
    assert "evidence_text" in serialized_item
    assert "max_effective_weight" in serialized_item
    assert "relevance" not in serialized_item
    assert "effective_weight" not in serialized_item


def test_body_only_relevance_is_preserved_as_prompt_evidence() -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    item = NewsItem(
        news_id="body-only",
        title="Market update",
        body="<p>Oil prices rise on supply concerns</p>",
        source="wire_reuters",
        published_at="2026-07-14T12:00:00Z",
    )

    digest = _weigher().weigh("run1", [item], TARGETS, now)

    assert digest.items[0].asset_weights["WTI"].relevance > 0
    assert digest.items[0].evidence_text == "Oil prices rise on supply concerns"


def test_global_cap_preserves_available_gold_and_wti_coverage() -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            news_id=f"btc-{index:02d}",
            title=f"Bitcoin update {index}",
            source="wire_reuters",
            published_at="2026-07-14T12:59:00Z",
            asset_tags=["BTC"],
        )
        for index in range(40)
    ]
    items.extend(
        [
            NewsItem(
                news_id="gold-coverage",
                title="Gold market update",
                source="wire_reuters",
                published_at="2026-07-13T13:00:00Z",
                asset_tags=["GOLD"],
            ),
            NewsItem(
                news_id="wti-coverage",
                title="Saudi Aramco increases crude exports",
                source="wire_reuters",
                published_at="2026-07-13T13:00:00Z",
            ),
        ]
    )

    first = _weigher().weigh("run1", items, TARGETS, now)
    second = _weigher().weigh("run1", list(reversed(items)), TARGETS, now)
    first_ids = [item.news_id for item in first.items]

    assert len(first.items) == 40
    assert "gold-coverage" in first_ids
    assert "wti-coverage" in first_ids
    assert first_ids == [item.news_id for item in second.items]


@pytest.mark.parametrize(
    ("published_at", "eligible"),
    [
        ("2026-07-14T01:00:00Z", True),  # 12 hours old
        ("2026-07-13T00:00:00Z", False),  # 37 hours old
        ("2026-07-14T13:00:01Z", False),  # future timestamp
        ("not-a-timestamp", False),
    ],
)
def test_news_freshness_eligibility(published_at: str, eligible: bool) -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    item = NewsItem(
        news_id="freshness",
        title="Bitcoin market update",
        source="wire_reuters",
        published_at=published_at,
        asset_tags=["BTC"],
    )

    digest = _weigher().weigh("run1", [item], TARGETS, now)

    assert bool(digest.items) is eligible


def test_stale_gold_news_is_not_restored_for_coverage() -> None:
    now = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(
            news_id=f"btc-fresh-{index:02d}",
            title=f"Bitcoin update {index}",
            source="wire_reuters",
            published_at="2026-07-14T12:59:00Z",
            asset_tags=["BTC"],
        )
        for index in range(40)
    ]
    items.append(
        NewsItem(
            news_id="gold-stale",
            title="Gold market update",
            source="wire_reuters",
            published_at="2026-07-12T13:00:00Z",
            asset_tags=["GOLD"],
        )
    )

    digest = _weigher().weigh("run1", items, TARGETS, now)

    assert "gold-stale" not in {item.news_id for item in digest.items}
