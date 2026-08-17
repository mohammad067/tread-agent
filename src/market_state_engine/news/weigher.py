"""Deterministic per-asset news weighting (F-6).

For every news item and every tracked asset:

    effective_weight =
        source_quality
        * asset_relevance
        * recency_decay

Responsibilities:
- Resolve deterministic source quality.
- Resolve deterministic recency decay.
- Obtain per-asset relevance from ``relevance.py``.
- Compute effective weight independently for each asset.
- Produce a deterministically ranked ``NewsDigest``.

Non-responsibilities:
- Asset detection / keyword classification.
- Macro-event detection.
- Sentiment direction.
- LLM-based weighting.

The LLM NEVER assigns relevance or effective weights.
"""

from __future__ import annotations

from datetime import datetime

from market_state_engine.config.models import HalfLives, SourceQuality
from market_state_engine.core.dtos import (
    AssetNewsWeight,
    NewsDigest,
    NewsItem,
    WeightedNewsItem,
)
from market_state_engine.features.decay import recency_decay

from .relevance import build_evidence_text, compute_relevance_map


class NewsWeigher:
    """Compute deterministic per-asset news weights."""

    def __init__(
        self,
        source_quality: SourceQuality,
        half_lives: HalfLives,
    ) -> None:
        self._sq = source_quality
        self._half_lives = half_lives

    def _quality(self, source: str) -> float:
        """Return configured quality for a source.

        Unknown sources use the configured deterministic default.
        """

        quality = self._sq.sources.get(
            source,
            self._sq.default_quality,
        )

        return max(0.0, min(1.0, float(quality)))

    def _half_life(self, event_type: str | None) -> float:
        """Return news half-life for the current event context."""

        table = self._half_lives.news_half_life_hours

        if event_type is not None:
            value = table.get(event_type)

            if value is not None:
                if value <= 0:
                    raise ValueError(
                        f"news half-life must be positive: "
                        f"event_type={event_type!r} value={value!r}"
                    )

                return float(value)

        default = float(table.get("default", 12.0))

        if default <= 0:
            raise ValueError(
                f"default news half-life must be positive: {default!r}"
            )

        return default

    @staticmethod
    def _normalize_target_assets(
        target_assets: set[str],
    ) -> set[str]:
        """Normalize target symbols before relevance/weight calculation."""

        return {
            asset.strip().upper()
            for asset in target_assets
            if asset and asset.strip()
        }

    @staticmethod
    def _effective_weight(
        source_quality: float,
        relevance: float,
        decay: float,
    ) -> float:
        """Compute one deterministic effective weight."""

        value = (
            float(source_quality)
            * float(relevance)
            * float(decay)
        )

        return max(0.0, min(1.0, value))

    def weigh(
        self,
        run_id: str,
        items: list[NewsItem],
        target_assets: set[str],
        now: datetime,
        default_event_type: str | None = None,
    ) -> NewsDigest:
        """Build a deterministic, per-asset weighted news digest."""

        targets = self._normalize_target_assets(target_assets)

        if not targets or not items:
            return NewsDigest(
                run_id=run_id,
                items=[],
                weighting_versions={
                    "source_quality": self._sq.version,
                    "half_lives": self._half_lives.version,
                    "relevance_model": "per_asset_v3",
                },
            )

        half_life = self._half_life(default_event_type)

        weighted: list[WeightedNewsItem] = []

        for item in items:
            quality = self._quality(item.source)

            decay = recency_decay(
                item.published_at,
                now,
                half_life,
            )

            decay = max(0.0, min(1.0, float(decay)))

            # -----------------------------------------------------------------
            # PRINCIPLE 1:
            # No keyword, tag or asset-classification logic belongs here.
            #
            # ``relevance.py`` is the single source of truth for deciding
            # which assets a news item is relevant to.
            # -----------------------------------------------------------------
            relevance_map = compute_relevance_map(
                item=item,
                target_assets=targets,
            )

            asset_weights: dict[str, AssetNewsWeight] = {}

            for asset in sorted(targets):
                relevance = max(
                    0.0,
                    min(
                        1.0,
                        float(relevance_map.get(asset, 0.0)),
                    ),
                )

                # Do not emit meaningless zero-relevance asset entries.
                if relevance <= 0.0:
                    continue

                # -------------------------------------------------------------
                # PRINCIPLE 2:
                # Effective weight is calculated independently PER ASSET.
                #
                # A Bitcoin article must not receive one global weight that is
                # later interpreted as equally relevant to ETH, GOLD or WTI.
                # -------------------------------------------------------------
                effective = self._effective_weight(
                    source_quality=quality,
                    relevance=relevance,
                    decay=decay,
                )

                asset_weights[asset] = AssetNewsWeight(
                    relevance=relevance,
                    effective_weight=effective,
                )

            # If the relevance layer says the article has no relationship to
            # any target asset, it does not belong in the NewsDigest.
            if not asset_weights:
                continue

            # -----------------------------------------------------------------
            # PRINCIPLE 3:
            # Weighting is ONLY:
            #
            #     source_quality
            #       x asset_relevance
            #       x recency_decay
            #
            # No sentiment, bullish/bearish direction, keyword heuristics or
            # LLM judgment is allowed in this layer.
            # -----------------------------------------------------------------
            max_effective_weight = max(
                weight.effective_weight
                for weight in asset_weights.values()
            )

            weighted.append(
                WeightedNewsItem(
                    news_id=item.news_id,
                    title=item.title,
                    evidence_text=build_evidence_text(item),
                    source=item.source,
                    published_at=item.published_at,
                    # Preserve the exact operands used above. Independently
                    # rounding operands and product would break the serialized
                    # multiplication invariant.
                    source_quality=quality,
                    recency_decay=decay,
                    asset_weights=asset_weights,
                    max_effective_weight=max_effective_weight,
                )
            )

        # Deterministic ranking:
        #
        # 1. strongest effective relevance to ANY tracked asset
        # 2. news_id as stable tie-break
        #
        # Ranking by the maximum asset weight is appropriate because the
        # digest is shared across all target assets. Per-asset consumers must
        # use ``asset_weights[asset].effective_weight`` rather than this
        # ranking helper.
        weighted.sort(
            key=lambda item: (
                -item.max_effective_weight,
                item.news_id,
            )
        )

        return NewsDigest(
            run_id=run_id,
            items=weighted,
            weighting_versions={
                "source_quality": self._sq.version,
                "half_lives": self._half_lives.version,
                "relevance_model": "per_asset_v3",
            },
        )
