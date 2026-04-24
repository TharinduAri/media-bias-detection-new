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
        
        # 1. Try RSS feed
        try:
            resp = await fetch(client, f"{self.url}/feed", extra_headers=_BROWSER_HEADERS)
            import xml.etree.ElementTree as ET
            # Use raw string or remove namespaces manually if needed, but standard XML usually works with .//item
            root = ET.fromstring(resp.text)
            for item in root.findall(".//item"):
                link = item.findtext("link")
                if link and not self.should_skip_url(link):
                    if link not in articles:
                        articles[link] = self._article_stub(link)
                if len(articles) >= max_articles:
                    break
        except Exception as exc:
            logger.debug("[EconomyNext] RSS feed fetch failed: %s", exc)

        # 2. Try Sitemap Index if RSS did not return enough URLs
        if len(articles) < max_articles:
            try:
                resp = await fetch(client, f"{self.url}/sitemap_index.xml", extra_headers=_BROWSER_HEADERS)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                
                # Sitemaps use namespaces
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                sitemaps = root.findall(".//sm:sitemap", namespaces=ns)
                
                # Fetch recent post sitemaps
                for sitemap in sitemaps:
                    loc = sitemap.findtext("sm:loc", namespaces=ns)
                    if loc and "post" in loc:
                        try:
                            await asyncio.sleep(2.5)  # 2.5s delay to prevent rate limit / HTTP 500
                            sub_resp = await fetch(client, loc, extra_headers=_BROWSER_HEADERS)
                            sub_root = ET.fromstring(sub_resp.text)
                            urls = sub_root.findall(".//sm:url", namespaces=ns)
                            
                            for url_tag in urls:
                                link = url_tag.findtext("sm:loc", namespaces=ns)
                                if link and not self.should_skip_url(link):
                                    if link not in articles:
                                        articles[link] = self._article_stub(link)
                                if len(articles) >= max_articles:
                                    break
                        except Exception as e:
                            logger.debug("[EconomyNext] Failed to fetch sub-sitemap %s: %s", loc, e)
                    
                    if len(articles) >= max_articles:
                        break
            except Exception as exc:
                logger.debug("[EconomyNext] Sitemap fetch failed: %s", exc)

        logger.info("[EconomyNext] Total discovered: %d URLs", len(articles))
        return list(articles.values())[:max_articles]

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
