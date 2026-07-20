"""NewsWeigher: effective_weight = source_quality x relevance x recency_decay. Pure (F-6).

The LLM never assigns these weights. Produces a NewsDigest ranked by effective_weight.
"""

from __future__ import annotations

from datetime import datetime

from market_state_engine.config.models import HalfLives, SourceQuality
from market_state_engine.core.dtos import NewsDigest, NewsItem, WeightedNewsItem
from market_state_engine.features.decay import recency_decay

from .relevance import compute_relevance


class NewsWeigher:
    def __init__(self, source_quality: SourceQuality, half_lives: HalfLives) -> None:
        self._sq = source_quality
        self._half_lives = half_lives

    def _quality(self, source: str) -> float:
        return self._sq.sources.get(source, self._sq.default_quality)

    def _half_life(self, event_type: str | None) -> float:
        table = self._half_lives.news_half_life_hours
        if event_type is not None and event_type in table:
            return table[event_type]
        return table.get("default", 12.0)

    def weigh(
        self,
        run_id: str,
        items: list[NewsItem],
        target_assets: set[str],
        now: datetime,
        default_event_type: str | None = None,
    ) -> NewsDigest:
        weighted: list[WeightedNewsItem] = []
        half_life = self._half_life(default_event_type)
        for item in items:
            quality = self._quality(item.source)
            relevance = compute_relevance(item, target_assets)
            decay = recency_decay(item.published_at, now, half_life)
            effective = quality * relevance * decay
            weighted.append(
                WeightedNewsItem(
                    news_id=item.news_id,
                    title=item.title,
                    source=item.source,
                    published_at=item.published_at,
                    source_quality=round(quality, 6),
                    relevance=round(relevance, 6),
                    recency_decay=round(decay, 6),
                    effective_weight=round(effective, 6),
                )
            )
        # Deterministic ranking: by effective_weight desc, tie-break by news_id.
        weighted.sort(key=lambda w: (-w.effective_weight, w.news_id))
        return NewsDigest(
            run_id=run_id,
            items=weighted,
            weighting_versions={
                "source_quality": self._sq.version,
                "half_lives": self._half_lives.version,
            },
        )
