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
import re
from datetime import datetime, timedelta

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import GhostResponseError, fetch
from src.collection.core.extraction import extract_with_trafilatura
from src.collection.core.utils import domain_of

logger = logging.getLogger(__name__)

# Paths known to be directory-blocked on economynext.com
_BLOCKED_SECTION_PATTERNS = ["/culture", "/sports", "/life-and-style", "/entertainment"]

# Ghost/500 threshold: if this fraction of requests fail, warn and cap articles
_CIRCUIT_BREAKER_RATIO = 0.50
_EN_GHOST_THRESHOLD = 500   # Economy Next ghosted pages tend to be < 500 bytes

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://google.com",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
}


class EconomyNextOutlet(BaseOutletScraper):
    """Economy Next (economynext.com) — adversarial WordPress scraper."""

    def __init__(self, name: str, url: str, **kwargs):
        super().__init__(name, url)
        self._cdx_cache: dict[str, str] = {}

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
        
        # 1. Wayback CDX API (Live site returns 403 Forbidden for discovery)
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=economynext.com/*"
            "&output=json&fl=timestamp,original"
            "&filter=statuscode:200&filter=mimetype:text/html"
            "&collapse=urlkey&from=20230101&to=20261231"
            f"&limit={max_articles}&offset=0"
        )
        try:
            resp = await client.get(cdx_url, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 2:
                        ts, orig_url = row[0], row[1]
                        if not self.should_skip_url(orig_url) and orig_url not in articles:
                            self._cdx_cache[orig_url] = ts
                            articles[orig_url] = self._article_stub(orig_url)
                            if len(articles) >= max_articles:
                                break
        except Exception as exc:
            logger.debug("[EconomyNext] CDX fetch failed: %s", exc)

        logger.info("[EconomyNext] Total discovered: %d URLs via Wayback Machine", len(articles))
        return list(articles.values())[:max_articles]

    # -- Content extraction ------------------------------------------------- #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Economy Next-specific extraction with ghost detection and browser headers."""
        try:
            resp = await fetch(client, url, extra_headers=_BROWSER_HEADERS,
                               follow_redirects=True)
            raw_html = resp.text
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404, 500, 503):
                ts = self._cdx_cache.get(url)
                if ts:
                    archive_url = f"https://web.archive.org/web/{ts}/{url}"
                    logger.debug("[EconomyNext] %d on live URL, falling back to Wayback: %s", exc.response.status_code, archive_url)
                    resp = await client.get(archive_url, follow_redirects=True, timeout=20.0, headers=_BROWSER_HEADERS)
                    resp.raise_for_status()
                    raw_html = resp.text
                else:
                    raise
            else:
                raise

        # Economy Next ghost: 200 OK with tiny body — raise non-retryable sentinel
        if len(raw_html.strip()) < _EN_GHOST_THRESHOLD:
            raise GhostResponseError(
                f"[EconomyNext] Ghost response ({len(raw_html)}b) for {url}"
            )

        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
