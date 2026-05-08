"""Daily Mirror scraper (dailymirror.lk).

One of Sri Lanka's largest English dailies. Custom PHP CMS.

Discovery:
  1. RSS feeds — multiple category feeds attempted
  2. Sitemap (/sitemap.xml or Google News sitemap)
  3. Homepage + section page link-scraping fallback

Article URL pattern:
  https://www.dailymirror.lk/{category}/{TITLE}/{category-id}-{article-id}
  e.g. https://www.dailymirror.lk/breaking-news/TITLE/108-295060
  These have 2+ path segments so pass is_article_url normally.

Note: Single-segment numeric IDs may appear in RSS; these are filtered
by should_skip_url but accepted here via override.
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

_RSS_CANDIDATES = [
    "/rss.xml",
    "/rss",
    "/feed",
    "/rss/breaking-news",
    "/rss/business",
    "/rss/political-news",
    "/rss/editorial",
    "/rss/top-story",
]
_SITEMAP_CANDIDATES = ["/sitemap.xml", "/news-sitemap.xml", "/sitemap_index.xml"]
_SECTION_PATHS = ["/", "/breaking-news/", "/business/", "/political-news/", "/top-story/"]

_ARTICLE_URL_RE = re.compile(
    r"https?://(?:www\.)?dailymirror\.lk/[a-z0-9\-]+/[^\"'\s<>]{5,}/\d+-\d+"
)


class DailyMirrorOutlet(BaseOutletScraper):
    """Daily Mirror (dailymirror.lk) — RSS primary, sitemap + homepage fallback."""

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
        logger.info("[DailyMirror] RSS: %d", len(articles))

        if len(articles) < max_articles:
            sm = await self._sitemap(client, days_back, max_articles - len(articles))
            for a in sm:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        if len(articles) < max_articles:
            hp = await self._section_scrape(client, max_articles - len(articles))
            for a in hp:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        logger.info("[DailyMirror] Total: %d", len(articles))
        return list(articles.values())[:max_articles]

    async def _rss(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        seen: set[str] = set()
        all_articles: list[dict[str, str]] = []

        for path in _RSS_CANDIDATES:
            if len(all_articles) >= max_articles:
                break
            root = await self._fetch_xml(client, f"{self.url}{path}")
            if root is None:
                continue
            for item in root.findall(".//item"):
                link = item.findtext("link")
                if not link or link in seen:
                    continue
                # Daily Mirror article links always contain a numeric ID suffix
                if not re.search(r"/\d+-\d+$", link):
                    continue
                pub = self._parse_dt(item.findtext("pubDate"))
                if pub and pub < cutoff:
                    continue
                title = item.findtext("title") or ""
                seen.add(link)
                all_articles.append(self._article_stub(link, pub, title))
                if len(all_articles) >= max_articles:
                    break

        return all_articles

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
                if not loc:
                    continue
                if not re.search(r"/\d+-\d+$", loc):
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

    async def _section_scrape(
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
                    if url not in articles:
                        articles[url] = self._article_stub(url)
                    if len(articles) >= max_articles:
                        break
            except Exception as exc:
                logger.debug("[DailyMirror] Section scrape %s failed: %s", path, exc)
        return list(articles.values())

    async def extract_content(self, url: str, client: httpx.AsyncClient) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
