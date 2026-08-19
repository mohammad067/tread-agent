"""Multi-market news ingestion via public RSS/Atom feeds.

Responsibilities of this module:
- Fetch configured public news feeds independently.
- Parse RSS/Atom entries defensively.
- Normalize entries into ``NewsItem`` records.
- Attach only trusted asset context declared by each feed.
- Deduplicate the same article across overlapping feeds.

Non-responsibilities:
- Sentiment scoring.
- Cross-market causal inference.
- News weighting.
- Per-asset relevance scoring.

Those concerns belong to downstream modules.

Important tagging rule:
A feed default tag is treated as trusted context only when the feed itself is
asset-specific, such as Cointelegraph's Bitcoin tag feed. Search queries and
general-purpose feeds must not receive forced asset tags.

Google News query results are never trusted asset context: a result may not
actually contain the query terms.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import cast

from market_state_engine.core.dtos import NewsItem
from market_state_engine.core.run_context import RunContext

_log = logging.getLogger("ingestion.real.news_feeds")


# ---------------------------------------------------------------------------
# Feed configuration
# ---------------------------------------------------------------------------
#
# Tuple format:
#   (url, source_id, trusted_default_asset_tags)
#
# ``trusted_default_asset_tags`` MUST only be populated when the feed/query
# itself guarantees a meaningful relationship with that asset.
#
# Examples:
# - /rss/tag/bitcoin          -> BTC is trusted
# - Google News query         -> no trusted asset
# - generic CoinDesk RSS      -> no trusted asset
# - generic Reuters energy    -> no trusted asset
#
_FEEDS: list[tuple[str, str, list[str]]] = [
    (
        "https://cointelegraph.com/rss/tag/bitcoin",
        "cointelegraph",
        ["BTC"],
    ),
    (
        "https://cointelegraph.com/rss/tag/ethereum",
        "cointelegraph",
        ["ETH"],
    ),
    (
        "https://cointelegraph.com/rss/tag/gold",
        "cointelegraph",
        ["GOLD"],
    ),
    # General CoinDesk feed. Do NOT force BTC/ETH tags.
    (
        "https://www.coindesk.com/arc/outboundfeeds/rss",
        "coindesk",
        [],
    ),
    # Google News search terms do not guarantee that every result is oil-related.
    # Reuters is source context only; downstream text relevance decides WTI.
    (
        "https://news.google.com/rss/search"
        "?q=(oil+OR+crude)+site:reuters.com"
        "&hl=en-US&gl=US&ceid=US:en",
        "reuters_via_gn",
        [],
    ),
    # General Reuters energy feed: electricity, renewables, grids, utilities,
    # etc. may appear here, so WTI must NOT be forced.
    (
        "https://news.google.com/rss/search"
        "?q=site:reuters.com/business/energy+when:1d"
        "&hl=en-US&gl=US&ceid=US:en",
        "reuters_via_gn",
        [],
    ),
]

_BODY_LIMIT = 2000
_TITLE_LIMIT = 500
_FETCH_TIMEOUT_SECONDS = 20.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _news_id(source: str, title: str, link: str) -> str:
    """Return a stable identifier for a normalized news item."""

    normalized_title = " ".join(title.split()).strip()
    normalized_link = link.strip()

    raw = f"{source}|{normalized_title}|{normalized_link}".encode(
        "utf-8",
        errors="replace",
    )
    return hashlib.sha256(raw).hexdigest()[:32]


def _format_utc(dt: datetime) -> str:
    """Normalize a datetime to the contract's UTC timestamp format."""

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_rss_date(text: str | None, fallback: datetime) -> str:
    """Parse RFC-2822/RSS or ISO-8601/Atom dates.

    ``fallback`` is injected by ``RunContext`` so replay does not depend on
    wall-clock time.
    """

    if not text or not text.strip():
        return _format_utc(fallback)

    raw = text.strip()

    # RSS commonly uses RFC-2822 dates.
    try:
        return _format_utc(parsedate_to_datetime(raw))
    except (TypeError, ValueError, OverflowError):
        pass

    # Atom commonly uses ISO-8601.
    try:
        iso = raw
        if iso.endswith("Z"):
            iso = f"{iso[:-1]}+00:00"

        return _format_utc(datetime.fromisoformat(iso))
    except (TypeError, ValueError, OverflowError):
        _log.debug("rss_date_parse_fail value=%r", raw)
        return _format_utc(fallback)


def _strip_html(text: str) -> str:
    """Remove simple HTML markup and normalize whitespace."""

    if not text:
        return ""

    without_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", without_tags).strip()


def _local(tag: str) -> str:
    """Return an XML tag name without its namespace."""

    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child(el: ET.Element, name: str) -> ET.Element | None:
    """Return the first direct XML child with the requested local name."""

    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _element_text(node: ET.Element | None) -> str:
    """Extract all textual content from an XML element."""

    if node is None:
        return ""

    return "".join(node.itertext()).strip()


def _child_text(el: ET.Element, name: str) -> str:
    return _element_text(_child(el, name))


def _link_of(item: ET.Element) -> str:
    """Extract a link from either RSS or Atom entries."""

    links = [child for child in item if _local(child.tag) == "link"]

    if not links:
        return ""

    # Prefer Atom's alternate/default link where available.
    for node in links:
        rel = (node.get("rel") or "alternate").strip().lower()
        href = (node.get("href") or "").strip()

        if href and rel == "alternate":
            return href

    # Fall back to any href/text value.
    for node in links:
        href = (node.get("href") or "").strip()
        if href:
            return href

        text = (node.text or "").strip()
        if text:
            return text

    return ""


def _fetch(
    url: str,
    timeout_s: float = _FETCH_TIMEOUT_SECONDS,
) -> bytes:
    """Fetch one RSS/Atom feed."""

    req = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "application/rss+xml, "
                "application/atom+xml, "
                "application/xml, "
                "text/xml, "
                "*/*"
            ),
            "User-Agent": "mse/0.1 (market-state-engine; research)",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return cast(bytes, resp.read())


def _entry_nodes(root: ET.Element) -> list[ET.Element]:
    """Return RSS ``item`` or Atom ``entry`` nodes.

    The search is namespace-agnostic and works with both common feed formats.
    """

    result: list[ET.Element] = []

    for node in root.iter():
        if _local(node.tag) in {"item", "entry"}:
            result.append(node)

    return result


def _parse_feed(
    content: bytes,
    source: str,
    trusted_defaults: list[str],
    fallback_time: datetime,
) -> list[NewsItem]:
    """Parse one RSS/Atom feed into normalized NewsItem objects."""

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        _log.warning(
            "rss_parse_fail source=%s err=%s",
            source,
            exc,
        )
        return []

    out: list[NewsItem] = []

    for node in _entry_nodes(root):
        title = _child_text(node, "title")
        title = re.sub(r"\s+", " ", title).strip()

        if not title:
            continue

        link = _link_of(node)

        description = (
            _child_text(node, "description")
            or _child_text(node, "summary")
            or _child_text(node, "content")
        )

        body_text = _strip_html(description)
        body = body_text[:_BODY_LIMIT] or None

        published = (
            _child_text(node, "pubDate")
            or _child_text(node, "published")
            or _child_text(node, "updated")
        )

        # Ingestion carries only trusted feed context. Text and macro
        # classification belong exclusively to the downstream relevance layer.
        tags = sorted({tag.strip().upper() for tag in trusted_defaults if tag.strip()})

        out.append(
            NewsItem(
                news_id=_news_id(
                    source=source,
                    title=title,
                    link=link,
                ),
                title=title[:_TITLE_LIMIT],
                source=source,
                published_at=_parse_rss_date(
                    published or None,
                    fallback=fallback_time,
                ),
                body=body,
                asset_tags=tags,
                relevance=None,
            )
        )

    return out


def _merge_duplicate(existing: NewsItem, incoming: NewsItem) -> NewsItem:
    """Merge duplicate articles observed through overlapping feeds.

    This matters for tag-specific feeds: the same Cointelegraph article may
    appear in both Bitcoin and Ethereum feeds. Silently keeping only the first
    copy would lose the second feed's trusted asset context.
    """

    merged_tags = sorted(
        set(existing.asset_tags or [])
        | set(incoming.asset_tags or [])
    )

    # Prefer the richer body, if one feed supplied more content.
    existing_body = existing.body or ""
    incoming_body = incoming.body or ""

    body = (
        incoming.body
        if len(incoming_body) > len(existing_body)
        else existing.body
    )

    # Prefer the earliest published timestamp if duplicated feeds disagree.
    published_at = min(
        existing.published_at,
        incoming.published_at,
    )

    return NewsItem(
        news_id=existing.news_id,
        title=existing.title,
        source=existing.source,
        published_at=published_at,
        body=body,
        asset_tags=merged_tags,
        relevance=None,
    )


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class RssNewsSource:
    """NewsSource-compatible RSS/Atom source for tracked markets."""

    def __init__(
        self,
        feeds: list[tuple[str, str, list[str]]] | None = None,
        max_items: int | None = None,
    ) -> None:
        if max_items is not None and max_items < 0:
            raise ValueError("max_items must be >= 0")

        self._feeds = (
            list(feeds)
            if feeds is not None
            else list(_FEEDS)
        )
        self._max_items = max_items

    def fetch_items(self, ctx: RunContext) -> list[NewsItem]:
        """Fetch, normalize, merge, rank and limit current news items."""

        if self._max_items == 0:
            return []

        collected: dict[str, NewsItem] = {}

        for url, source, trusted_defaults in self._feeds:
            try:
                raw = _fetch(url)

                batch = _parse_feed(
                    content=raw,
                    source=source,
                    trusted_defaults=trusted_defaults,
                    fallback_time=ctx.now,
                )

                _log.info(
                    "rss_ok source=%s url=%s n=%s",
                    source,
                    url,
                    len(batch),
                )

            except Exception as exc:
                # Feed isolation is deliberate: one external source failing
                # must not make the complete market-state run fail.
                _log.warning(
                    "rss_fail source=%s url=%s err=%s",
                    source,
                    url,
                    exc,
                )
                continue

            for item in batch:
                existing = collected.get(item.news_id)

                if existing is None:
                    collected[item.news_id] = item
                else:
                    collected[item.news_id] = _merge_duplicate(
                        existing,
                        item,
                    )

        items = list(collected.values())

        # Contract timestamps are normalized UTC ISO strings, therefore
        # lexicographic ordering is chronological.
        #
        # news_id provides a deterministic tie-break for identical timestamps.
        items.sort(
            key=lambda item: (
                item.published_at,
                item.news_id,
            ),
            reverse=True,
        )

        # Production leaves candidate limiting to the downstream deterministic
        # selection policy, after per-asset relevance is known. An explicit
        # limit remains available for callers that intentionally request one.
        if self._max_items is None:
            return items
        return items[: self._max_items]
