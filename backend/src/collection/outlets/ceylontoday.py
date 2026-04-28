"""Ceylon Today scraper.

Discovery strategy:
  1. Sitemap (follows the 301 redirect on /sitemap.xml → canonical sitemap location)
  2. RSS feed fallback (/feed or /rss)

Known issues from audit:
  - /sitemap.xml returns 301 (sitemap moved) — httpx follows redirects automatically
  - No special content quirks; trafilatura handles the HTML well

Content extraction: standard trafilatura pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import GhostResponseError, fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_RSS_CANDIDATES = ["/feed", "/rss", "/feed/rss2", "/rss.xml"]


class CeylonTodayOutlet(BaseOutletScraper):
    """Ceylon Today (ceylontoday.lk) — sitemap with 301 redirect handling."""

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        # Primary: sitemap (client follows 301 automatically)
        sitemap_urls = await self._sitemap_traverse(client, days_back, max_articles)
        for art in sitemap_urls:
            articles[art["url"]] = art
        logger.info("[CeylonToday] Sitemap: %d URLs", len(articles))

        # Fallback: RSS
        if len(articles) < max(20, max_articles // 6):
            rss_urls = await self._rss_discover(client, days_back, max_articles)
            for art in rss_urls:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            if rss_urls:
                logger.info("[CeylonToday] RSS added %d URLs", len(rss_urls))

        return list(articles.values())[:max_articles]

    # -- Sitemap ------------------------------------------------------------ #

    async def _sitemap_traverse(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        # follow_redirects=True handles the 301 sitemap move
        root = await self._fetch_xml(client, f"{self.url}/sitemap.xml")
        if root is None:
            return []

        # Could be sitemapindex or urlset
        urls: dict[str, dict[str, str]] = {}
        shard_queue: list[str] = []

        if self._tag(root.tag) == "sitemapindex":
            for child in root:
                if self._tag(child.tag) != "sitemap":
                    continue
                for node in child:
                    if self._tag(node.tag) == "loc" and node.text:
                        shard_queue.append(node.text.strip())
        else:
            shard_queue = [f"{self.url}/sitemap.xml"]

        import asyncio
        batch_size = 10
        for i in range(0, len(shard_queue), batch_size):
            if len(urls) >= max_articles:
                break
            batch = shard_queue[i:i + batch_size]
            roots = await asyncio.gather(*[self._fetch_xml(client, u) for u in batch])
            for shard_root in roots:
                if shard_root is None or self._tag(shard_root.tag) != "urlset":
                    continue
                for child in shard_root:
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

    # -- RSS fallback ------------------------------------------------------- #

    async def _rss_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        import xml.etree.ElementTree as ET
        cutoff = datetime.now() - timedelta(days=days_back)

        for path in _RSS_CANDIDATES:
            try:
                resp = await fetch(client, f"{self.url}{path}")
                root = ET.fromstring(resp.text)
            except Exception:
                continue

            items: list[dict[str, str]] = []
            channel = root.find("channel")
            entries = channel.findall("item") if channel is not None else root.findall(".//item")
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
            if items:
                return items

        return []

    # -- Content ------------------------------------------------------------ #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
