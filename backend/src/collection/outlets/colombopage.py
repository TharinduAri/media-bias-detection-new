"""Colombo Page scraper (colombopage.com).

English-language online news portal. Custom CMS.

Article URL pattern:
  https://www.colombopage.com/archive_YYA/MonDD_TIMESTAMP_ID.php
  e.g. https://www.colombopage.com/archive_25A/May25_1748273066CH.php
  Two path segments → passes is_article_url.

Discovery:
  1. RSS feed (/rss.xml, /rss, /feed)
  2. Sitemap (/sitemap.xml)
  3. Archive page link-scraping fallback — Colombo Page uses a flat archive
     structure that is easy to parse by regex
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_RSS_CANDIDATES = ["/rss.xml", "/rss", "/feed", "/feed/rss2"]
_SITEMAP_CANDIDATES = ["/sitemap.xml", "/news-sitemap.xml"]
_ARCHIVE_PATHS = ["/", "/latest_news/"]

# archive_YYA/MonDD_TIMESTAMP_ID.php
_ARTICLE_URL_RE = re.compile(
    r"https?://(?:www\.)?colombopage\.com/archive_\w+/\w+\.php"
)


class ColomboPageOutlet(BaseOutletScraper):
    """Colombo Page (colombopage.com) — RSS primary, archive-page fallback."""

    def should_skip_url(self, url: str) -> bool:
        # Accept .php archive URLs which may fail the generic segment check
        if re.search(r"colombopage\.com/archive_\w+/\w+\.php$", url):
            return False
        return super().should_skip_url(url)

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        rss = await self._rss(client, days_back, max_articles)
        for a in rss:
            articles[a["url"]] = a
        logger.info("[ColomboPage] RSS: %d", len(articles))

        if len(articles) < max_articles:
            sm = await self._sitemap(client, days_back, max_articles - len(articles))
            for a in sm:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        if len(articles) < max_articles:
            hp = await self._archive_scrape(client, max_articles - len(articles))
            for a in hp:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        logger.info("[ColomboPage] Total: %d", len(articles))
        return list(articles.values())[:max_articles]

    async def _rss(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        for path in _RSS_CANDIDATES:
            root = await self._fetch_xml(client, f"{self.url}{path}")
            if root is None:
                continue
            articles: list[dict[str, str]] = []
            for item in root.findall(".//item"):
                link = item.findtext("link")
                if not link or self.should_skip_url(link):
                    continue
                pub = self._parse_dt(item.findtext("pubDate"))
                if pub and pub < cutoff:
                    continue
                title = item.findtext("title") or ""
                articles.append(self._article_stub(link, pub, title))
                if len(articles) >= max_articles:
                    break
            if articles:
                return articles
        return []

    async def _sitemap(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        for path in _SITEMAP_CANDIDATES:
            root = await self._fetch_xml(client, f"{self.url}{path}")
            if root is None:
                continue
            articles: dict[str, dict[str, str]] = {}
            for child in root.iter():
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
            if articles:
                return list(articles.values())
        return []

    async def _archive_scrape(
        self, client: httpx.AsyncClient, max_articles: int
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        for path in _ARCHIVE_PATHS:
            if len(articles) >= max_articles:
                break
            try:
                resp = await fetch(client, f"{self.url}{path}")
                for match in _ARTICLE_URL_RE.finditer(resp.text):
                    url = match.group(0).rstrip("\"'")
                    if url not in articles:
                        articles[url] = self._article_stub(url)
                    if len(articles) >= max_articles:
                        break
            except Exception as exc:
                logger.debug("[ColomboPage] Archive scrape %s failed: %s", path, exc)
        return list(articles.values())

    async def extract_content(self, url: str, client: httpx.AsyncClient) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
