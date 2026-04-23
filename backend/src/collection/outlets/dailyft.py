"""Daily FT scraper.

Discovery strategy:
  1. Custom sitemap endpoint: /sitemaps/english-{page} (0-indexed, paginated)
     Each page is a plain urlset XML containing up to 300 article URLs.
     Traverse pages until fewer than 300 URLs returned (end of pagination).
  2. RSS feed fallback: /feed

Content extraction: standard trafilatura (Daily FT HTML is clean and well-structured).

Known info from audit:
  - /sitemaps/english-0 resolved 300 article URLs successfully
  - No ghost responses or 403 issues observed
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from .base import BaseOutletScraper, fetch, extract_with_trafilatura

logger = logging.getLogger(__name__)

_SITEMAP_PAGE_SIZE = 300       # Daily FT returns exactly this many per page
_MAX_SITEMAP_PAGES = 20        # Safety cap: 20 × 300 = 6,000 URLs max


class DailyFTOutlet(BaseOutletScraper):
    """Daily FT (ft.lk) — paginated /sitemaps/english-N discovery."""

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        cutoff = datetime.now() - timedelta(days=days_back)

        # Determine how many pages to fetch by probing concurrently.
        # Start with pages 0..4 in the first batch, then continue if full.
        page = 0
        while len(articles) < max_articles and page < _MAX_SITEMAP_PAGES:
            # Fetch a batch of pages concurrently
            batch_size = min(5, _MAX_SITEMAP_PAGES - page)
            pages_to_fetch = list(range(page, page + batch_size))
            roots = await asyncio.gather(
                *[self._fetch_xml(client, f"{self.url}/sitemaps/english-{p}")
                  for p in pages_to_fetch]
            )

            got_full_page = False
            for p, root in zip(pages_to_fetch, roots):
                if root is None or self._tag(root.tag) != "urlset":
                    continue

                page_count = 0
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
                    page_count += 1
                    if len(articles) >= max_articles:
                        break

                if page_count >= _SITEMAP_PAGE_SIZE:
                    got_full_page = True

            page += batch_size
            if not got_full_page:
                break  # Reached the last (partial) page

        logger.info("[DailyFT] Discovered %d article URLs", len(articles))
        return list(articles.values())[:max_articles]

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
