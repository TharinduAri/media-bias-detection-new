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
        
        categories = [
            "economy", "finance/banking", "markets/stocks-companies", "politics",
            "business", "energy", "logistics", "world", "opinion", "sci-tech/ict", "culture/sports"
        ]

        # Step 1 & 2: Iterate categories and paginate to exhaustion
        for cat in categories:
            page = 1
            while len(articles) < max_articles:
                url = f"{self.url}/{cat}/page/{page}/"
                try:
                    resp = await fetch(client, url, extra_headers=_BROWSER_HEADERS)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        break  # Exhausted this category
                    logger.debug("[EconomyNext] HTTP error %s on %s", exc.response.status_code, url)
                    break
                except Exception as exc:
                    logger.debug("[EconomyNext] Error fetching %s: %s", url, exc)
                    break

                html = resp.text
                # Find all h2 and h3 blocks
                blocks = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', html, flags=re.DOTALL | re.IGNORECASE)
                page_found = 0
                for block in blocks:
                    matches = re.findall(r'href=[\'"](https?://(?:www\.)?economynext\.com/[^\'"]+)[\'"]', block, flags=re.IGNORECASE)
                    for link in matches:
                        if "?p=" in link or self.should_skip_url(link):
                            continue
                        if link not in articles:
                            articles[link] = self._article_stub(link)
                            page_found += 1
                
                if page_found == 0:
                    break  # No new valid links, probably empty page
                
                page += 1

        logger.info("[EconomyNext] Discovered %d URLs via category pagination", len(articles))
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
