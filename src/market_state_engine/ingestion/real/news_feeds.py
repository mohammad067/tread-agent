"""Multi-market news via public RSS feeds.

Each feed is isolated: a failed fetch does not stop the others. Feed entries
are normalized into ``NewsItem`` records; deterministic weighting happens later.
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

# (url, source_id برای source_quality.yaml, تگ‌های پیش‌فرض فید)
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
    (
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "coindesk",
        ["BTC", "ETH"],
    ),
    # Oil / energy via Google News → Reuters (no API key)
    (
        "https://news.google.com/rss/search?q=(oil+OR+crude)+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
        "reuters_via_gn",
        ["WTI"],
    ),
    (
        "https://news.google.com/rss/search?q=site:reuters.com/business/energy+when:1d&hl=en-US&gl=US&ceid=US:en",
        "reuters_via_gn",
        ["WTI"],
    ),
]

_MAX_ITEMS = 40

_TAG_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("BTC", ("bitcoin", "btc", "satoshi")),
    ("ETH", ("ethereum", "vitalik", " ether")),
    ("GOLD", (" gold", "xau", "bullion", "tether gold", "pax gold")),
    ("WTI", ("crude", "oil price", "wti", "brent", "opec", "petroleum")),
    ("TOTAL_MCAP", ("fed", "fomc", "cpi", "inflation", "rate hike", "rate cut", "sec ")),
]


def _news_id(source: str, title: str, link: str) -> str:
    raw = f"{source}|{title}|{link}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:32]


def _parse_rss_date(text: str | None) -> str:
    if not text:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _child_text(el: ET.Element, name: str) -> str:
    node = _child(el, name)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _link_of(item: ET.Element) -> str:
    node = _child(item, "link")
    if node is None:
        return ""
    return (node.get("href") or node.text or "").strip()


def _tags_from_text(title: str, body: str, defaults: list[str]) -> list[str]:
    blob = f" {title} {body} ".lower()
    tags = set(defaults)
    for asset, keys in _TAG_KEYWORDS:
        if any(k in blob for k in keys):
            tags.add(asset)
    return sorted(tags)


def _fetch(url: str, timeout_s: float = 20.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "User-Agent": "mse/0.1 (market-state-engine; research)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return cast(bytes, resp.read())


def _parse_feed(content: bytes, source: str, defaults: list[str]) -> list[NewsItem]:
    out: list[NewsItem] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        _log.warning("rss_parse_fail source=%s err=%s", source, exc)
        return out

    channel = _child(root, "channel")
    items = list(channel) if channel is not None else list(root)
    for node in items:
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _child_text(node, "title")
        if not title:
            continue
        link = _link_of(node)
        desc = _child_text(node, "description") or _child_text(node, "summary")
        body = _strip_html(desc)[:2000] or None
        pub = _child_text(node, "pubDate") or _child_text(node, "published")
        tags = _tags_from_text(title, body or "", defaults)
        if not tags:
            continue
        out.append(
            NewsItem(
                news_id=_news_id(source, title, link),
                title=title[:500],
                source=source,
                published_at=_parse_rss_date(pub or None),
                body=body,
                asset_tags=tags,
                relevance=None,
            )
        )
    return out


class RssNewsSource:
    """NewsSource-compatible for crypto, gold, and energy (WTI) feeds."""

    def __init__(
        self,
        feeds: list[tuple[str, str, list[str]]] | None = None,
        max_items: int = _MAX_ITEMS,
    ) -> None:
        self._feeds = feeds if feeds is not None else list(_FEEDS)
        self._max_items = max_items

    def fetch_items(self, ctx: RunContext) -> list[NewsItem]:
        collected: list[NewsItem] = []
        seen: set[str] = set()
        for url, source, defaults in self._feeds:
            try:
                raw = _fetch(url)
                batch = _parse_feed(raw, source, defaults)
                _log.info("rss_ok source=%s url=%s n=%s", source, url, len(batch))
            except Exception as exc:
                _log.warning("rss_fail source=%s url=%s err=%s", source, url, exc)
                continue
            for item in batch:
                if item.news_id in seen:
                    continue
                seen.add(item.news_id)
                collected.append(item)
        collected.sort(key=lambda x: x.published_at, reverse=True)
        return collected[: self._max_items]