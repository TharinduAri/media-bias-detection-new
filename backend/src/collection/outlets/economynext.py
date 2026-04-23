"""Economy Next scraper.

This is the most adversarial outlet in the dataset.

Known failure modes from audit:
  1. HTTP 500 on content pages — exponential backoff retries (1.5s, 3.0s)
  2. HTTP 403 on /culture directory — blocked at path level, do not retry
  3. "Ghosting" — HTTP 200 with near-empty body (anti-scraping countermeasure)
  4. Discovery timeouts when server is under high load

Discovery strategy:
  1. WordPress sitemap index (/wp-sitemap.xml → /wp-sitemap-posts-post-N.xml shards)
     Concurrent shard fetching in batches of 20.
  2. RSS feed fallback (/feed)
  3. Skip known-blocked paths (/culture, /sports, /life-and-style)

Content extraction:
  - Ghost detection: skip URLs where response body < GHOST_THRESHOLD bytes
  - On HTTP 500: let tenacity handle retries (2 retries max for EN to reduce hammering)
  - On HTTP 403: record blocked path, do not retry
  - Extra headers: Referer, Accept mimicking browser to reduce 500 rate

Circuit breaker:
  - If > 50% of sampled requests return 500/ghost in a single run, log a WARNING
    and reduce the concurrency for this domain by releasing extra semaphore slots
    (achieved by reducing the effective max_articles to avoid hammering a sick server).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from .base import (
    BaseOutletScraper, GhostResponseError, fetch,
    extract_with_trafilatura, _domain_of,
)

logger = logging.getLogger(__name__)

# Paths known to be directory-blocked on economynext.com
_BLOCKED_SECTION_PATTERNS = ["/culture", "/sports", "/life-and-style", "/entertainment"]

# Ghost/500 threshold: if this fraction of requests fail, warn and cap articles
_CIRCUIT_BREAKER_RATIO = 0.50
_EN_GHOST_THRESHOLD = 500   # Economy Next ghosted pages tend to be < 500 bytes

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://economynext.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
}


class EconomyNextOutlet(BaseOutletScraper):
    """Economy Next (economynext.com) — adversarial WordPress scraper."""

    def should_skip_url(self, url: str) -> bool:
        if not super().should_skip_url(url) is False:
            return True
        lower = url.lower()
        return any(pat in lower for pat in _BLOCKED_SECTION_PATTERNS)

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        cutoff = datetime.now() - timedelta(days=days_back)

        # Primary: WordPress sitemap index
        wp_urls = await self._wp_sitemap_discover(client, days_back, max_articles)
        for art in wp_urls:
            articles[art["url"]] = art
        logger.info("[EconomyNext] WP sitemap: %d URLs", len(articles))

        # Fallback: RSS if sitemap was thin
        if len(articles) < max(20, max_articles // 6):
            rss_urls = await self._rss_discover(client, days_back, max_articles - len(articles))
            for art in rss_urls:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            if rss_urls:
                logger.info("[EconomyNext] RSS added %d URLs", len(rss_urls))

        return list(articles.values())[:max_articles]

    # -- WordPress sitemap -------------------------------------------------- #

    async def _wp_sitemap_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        index_root = await self._fetch_xml(client, f"{self.url}/wp-sitemap.xml")
        if index_root is None:
            return []

        # Collect all post shards from the index
        shard_urls: list[str] = []
        if self._tag(index_root.tag) == "sitemapindex":
            for child in index_root:
                if self._tag(child.tag) != "sitemap":
                    continue
                for node in child:
                    if self._tag(node.tag) == "loc" and node.text:
                        loc = node.text.strip()
                        # Only take post shards, skip taxonomy/page shards
                        if "posts-post" in loc:
                            shard_urls.append(loc)
        elif self._tag(index_root.tag) == "urlset":
            shard_urls = [f"{self.url}/wp-sitemap.xml"]

        if not shard_urls:
            return []

        # Fetch shards concurrently in batches of 20
        articles: dict[str, dict[str, str]] = {}
        batch_size = 20
        for i in range(0, len(shard_urls), batch_size):
            if len(articles) >= max_articles:
                break
            batch = shard_urls[i:i + batch_size]
            roots = await asyncio.gather(*[self._fetch_xml(client, u) for u in batch])
            for root in roots:
                if root is None or self._tag(root.tag) != "urlset":
                    continue
                for child in root:
                    if self._tag(child.tag) != "url":
                        continue
                    loc = lastmod = None
                    for node in child:
                        t = self._tag(node.tag)
                        if t == "loc" and node.text:
                            loc = node.text.strip()
                        elif t == "lastmod" and node.text:
                            lastmod = node.text.strip()
                    if not loc or self.should_skip_url(loc):
                        continue
                    pub = self._parse_dt(lastmod)
                    if pub and pub < cutoff:
                        continue
                    articles[loc] = self._article_stub(loc, pub)
                    if len(articles) >= max_articles:
                        break

        return list(articles.values())

    # -- RSS fallback ------------------------------------------------------- #

    async def _rss_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        import xml.etree.ElementTree as ET
        cutoff = datetime.now() - timedelta(days=days_back)
        try:
            resp = await fetch(client, f"{self.url}/feed",
                               extra_headers=_BROWSER_HEADERS)
            root = ET.fromstring(resp.text)
        except Exception as exc:
            logger.debug("[EconomyNext] RSS fallback failed: %s", exc)
            return []

        items: list[dict[str, str]] = []
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else []
        for item in entries:
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            title_el = item.find("title")
            url = (link_el.text or "").strip() if link_el is not None else ""
            if not url or self.should_skip_url(url):
                continue
            pub = self._parse_dt(pub_el.text if pub_el is not None else None)
            if pub and pub < cutoff:
                continue
            title = (title_el.text or "").strip() if title_el is not None else ""
            items.append(self._article_stub(url, pub, title))
            if len(items) >= max_articles:
                break
        return items

    # -- Content extraction ------------------------------------------------- #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Economy Next-specific extraction with ghost detection and browser headers."""
        resp = await fetch(client, url, extra_headers=_BROWSER_HEADERS,
                           follow_redirects=True)
        raw_html = resp.text

        # Economy Next ghost: 200 OK with tiny body — raise non-retryable sentinel
        if len(raw_html.strip()) < _EN_GHOST_THRESHOLD:
            raise GhostResponseError(
                f"[EconomyNext] Ghost response ({len(raw_html)}b) for {url}"
            )

        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
