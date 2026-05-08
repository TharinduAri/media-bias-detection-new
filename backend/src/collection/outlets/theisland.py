"""The Island scraper (island.lk).

One of Sri Lanka's oldest English-language dailies (Upali Group).
Custom CMS — not WordPress.

Discovery:
  1. RSS feed (/rss.xml, /rss, /feed) — most reliable
  2. Standard sitemap (/sitemap.xml, /sitemap_index.xml)
  3. Homepage + section page regex link-scraping fallback

Article URL pattern: https://island.lk/YYYY/MM/DD/slug/
  or: https://island.lk/?p=NNNNN
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

_RSS_CANDIDATES = ["/rss.xml", "/rss", "/feed", "/rss2", "/?feed=rss2"]
_SITEMAP_CANDIDATES = ["/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml"]
_SECTION_PATHS = ["/", "/local/", "/business/", "/opinion/", "/sports/"]

_ARTICLE_URL_RE = re.compile(
    r"https?://(?:www\.)?island\.lk/(?:\d{4}/\d{2}/\d{2}/[a-z0-9\-]+/?|\?p=\d+)"
)


class TheIslandOutlet(BaseOutletScraper):
    """The Island (island.lk) — RSS primary, sitemap + homepage fallback."""

    def should_skip_url(self, url: str) -> bool:
        if not super().should_skip_url(url):
            return False
        # Accept ?p=NNNNN style article IDs which base filter may reject
        return "island.lk/?p=" not in url

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
        logger.info("[TheIsland] RSS: %d", len(articles))

        if len(articles) < max_articles:
            sm = await self._sitemap(client, days_back, max_articles - len(articles))
            for a in sm:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        if len(articles) < max_articles:
            hp = await self._homepage_scrape(client, max_articles - len(articles))
            for a in hp:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        logger.info("[TheIsland] Total: %d", len(articles))
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
                logger.debug("[TheIsland] RSS hit: %s (%d)", path, len(articles))
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
            tag = self._tag(root.tag)

            # Sitemap index — recurse into child sitemaps
            if tag == "sitemapindex":
                child_urls: list[str] = []
                for child in root:
                    if self._tag(child.tag) == "sitemap":
                        for node in child:
                            if self._tag(node.tag) == "loc" and node.text:
                                child_urls.append(node.text.strip())
                for child_url in child_urls[:10]:
                    if len(articles) >= max_articles:
                        break
                    child_root = await self._fetch_xml(client, child_url)
                    if child_root is None:
                        continue
                    for child in child_root:
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

            # Flat urlset
            elif tag == "urlset":
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

            if articles:
                return list(articles.values())
        return []

    async def _homepage_scrape(
        self, client: httpx.AsyncClient, max_articles: int
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        for path in _SECTION_PATHS:
            if len(articles) >= max_articles:
                break
            try:
                resp = await fetch(client, f"{self.url}{path}")
                for match in _ARTICLE_URL_RE.finditer(resp.text):
                    url = match.group(0).rstrip("\"'")
                    if url not in articles and not self.should_skip_url(url):
                        articles[url] = self._article_stub(url)
                    if len(articles) >= max_articles:
                        break
            except Exception as exc:
                logger.debug("[TheIsland] Homepage scrape %s failed: %s", path, exc)
        return list(articles.values())

    async def extract_content(self, url: str, client: httpx.AsyncClient) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
