"""Ada Derana scraper.

Discovery strategy (in priority order):
  1. Sitemap traversal (standard urlset)
  2. Wayback Machine CDX API (fallback — covers URLs blocked by live server)

Content extraction quirks:
  - Article URLs use legacy form: /news.php?nid=XXXXX → follow 301 to canonical
  - Extract with trafilatura (works well for Derana's HTML structure)
  - Wayback Machine fetches use web.archive.org mirror to bypass live blocks

Known issues from audit:
  - Wayback lookup occasionally fails (external service) — treated as INFO, not WARNING
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import GhostResponseError, fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"


class AdaDeranaOutlet(BaseOutletScraper):
    """Ada Derana (adaderana.lk) — sitemap-first + Wayback CDX fallback."""

    # Derana beautifies /news.php?nid=X → /YYYY/MM/DD/slug/  via 301.
    # The sitemap already contains the canonical slugged URLs, so no special
    # rewriting is needed at discovery; the HTTP client follows redirects.

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        # --- Primary: sitemap ---
        sitemap_urls = await self._sitemap_discover(client, days_back, max_articles)
        for art in sitemap_urls:
            articles[art["url"]] = art
        logger.info("[AdaDerana] Sitemap: %d URLs", len(articles))

        # --- Fallback: Wayback CDX ---
        if len(articles) < max(30, max_articles // 4):
            wayback_urls = await self._wayback_discover(client, days_back, max_articles)
            for art in wayback_urls:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            logger.info("[AdaDerana] Wayback added %d URLs (total: %d)",
                        len(wayback_urls), len(articles))

        return list(articles.values())[:max_articles]

    # -- Sitemap ------------------------------------------------------------ #

    async def _sitemap_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        sitemap_url = f"{self.url}/sitemap.xml"
        root = await self._fetch_xml(client, sitemap_url)
        if root is None:
            return []

        urls: dict[str, dict[str, str]] = {}
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
            urls[loc] = self._article_stub(loc, pub)
            if len(urls) >= max_articles:
                break

        return list(urls.values())

    # -- Wayback CDX -------------------------------------------------------- #

    async def _wayback_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        domain = urlparse(self.url).netloc.lstrip("www.")
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=days_back)).strftime("%Y%m%d")
        until = now.strftime("%Y%m%d")
        params = {
            "url": f"{domain}/*",
            "output": "json",
            "fl": "timestamp,original,statuscode",
            "filter": "statuscode:200",
            "collapse": "urlkey",
            "from": since,
            "to": until,
            "limit": str(max_articles * 2),
        }
        try:
            resp = await client.get(_WAYBACK_CDX, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            logger.info("[AdaDerana][WAYBACK] Lookup unavailable: %s", exc)
            return []

        if not isinstance(rows, list) or len(rows) <= 1:
            return []

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows[1:]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts, original_url = str(row[0]).strip(), str(row[1]).strip()
            if not original_url or original_url in seen or self.should_skip_url(original_url):
                continue
            try:
                dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
            except ValueError:
                dt = datetime.now()
            seen.add(original_url)
            items.append(self._article_stub(original_url, dt))
            if len(items) >= max_articles:
                break

        return items

    # -- Content extraction ------------------------------------------------- #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Follow any 301 redirect (news.php?nid= → canonical) then trafilatura."""
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
