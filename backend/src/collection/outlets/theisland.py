"""The Island scraper (island.lk).

WordPress CMS (confirmed). Use `island.lk` — `www.island.lk` is non-functional.

URL pattern: https://island.lk/{slug}/ — clean WP permalinks, no date in path.
Single-segment slugs are NOT caught by the generic is_article_url filter, so
should_skip_url is overridden to accept them.

Discovery:
  1. RSS feed (/feed/) — WordPress default, most reliable
  2. WP REST API (/wp-json/wp/v2/posts)
  3. XML Sitemap (/wp-sitemap.xml, /sitemap.xml)
  4. Homepage link-scraping fallback
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_WP_API_PATH = "/wp-json/wp/v2/posts"
_WP_FIELDS = "id,date,title,link,content"
_WP_PER_PAGE = 100

_RSS_CANDIDATES = ["/feed/", "/feed", "/rss", "/rss.xml"]
_SITEMAP_CANDIDATES = ["/wp-sitemap.xml", "/sitemap.xml"]

# Single-segment slugs like /the-root-of-all-evil/
_SLUG_RE = re.compile(r"https?://island\.lk/([a-z0-9][a-z0-9\-]{4,})/?$")


class TheIslandOutlet(BaseOutletScraper):
    """The Island (island.lk) — WordPress, RSS primary."""

    def should_skip_url(self, url: str) -> bool:
        if not super().should_skip_url(url):
            return False
        # Accept single-segment WP permalink slugs rejected by the generic 2-segment rule
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        path = (parsed.path or "").strip("/")
        if domain == "island.lk" and path and "/" not in path and len(path) >= 5:
            return False
        return True

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        # 1. RSS (most reliable for WordPress)
        rss = await self._rss(client, days_back, max_articles)
        for a in rss:
            articles[a["url"]] = a
        logger.info("[TheIsland] RSS: %d", len(articles))

        # 2. WP REST API
        if len(articles) < max_articles:
            api = await self._wp_api(client, days_back, max_articles - len(articles))
            for a in api:
                if a["url"] not in articles:
                    articles[a["url"]] = a
            if api:
                logger.info("[TheIsland] WP API added %d", len(api))

        # 3. Sitemap
        if len(articles) < max_articles:
            sm = await self._sitemap(client, days_back, max_articles - len(articles))
            for a in sm:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        # 4. Homepage regex fallback
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

    async def _wp_api(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        endpoint = f"{self.url}{_WP_API_PATH}"
        articles: list[dict[str, str]] = []

        for page in range(1, 10):
            if len(articles) >= max_articles:
                break
            params = urlencode({
                "_fields": _WP_FIELDS,
                "per_page": str(_WP_PER_PAGE),
                "page": str(page),
                "orderby": "date",
                "order": "desc",
            })
            try:
                resp = await fetch(client, f"{endpoint}?{params}")
                posts = resp.json()
            except Exception as exc:
                logger.debug("[TheIsland] WP API page %d failed: %s", page, exc)
                break

            if not isinstance(posts, list) or not posts:
                break

            for post in posts:
                if not isinstance(post, dict):
                    continue
                url = (post.get("link") or "").strip()
                if not url or self.should_skip_url(url):
                    continue
                pub = self._parse_dt(post.get("date"))
                if pub and pub < cutoff:
                    continue
                content_obj = post.get("content")
                title_obj = post.get("title")
                raw_html = content_obj.get("rendered", "") if isinstance(content_obj, dict) else ""
                title = self._strip_html(title_obj.get("rendered", "") if isinstance(title_obj, dict) else "")
                text = self._strip_html(raw_html)
                stub = self._article_stub(url, pub, title)
                if text and len(text) >= 50:
                    stub["text"] = text
                    stub["raw_html"] = raw_html
                articles.append(stub)
                if len(articles) >= max_articles:
                    break

            if len(posts) < _WP_PER_PAGE:
                break

        return articles

    async def _sitemap(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        for path in _SITEMAP_CANDIDATES:
            root = await self._fetch_xml(client, f"{self.url}{path}")
            if root is None:
                continue
            tag = self._tag(root.tag)
            articles: dict[str, dict[str, str]] = {}

            if tag == "sitemapindex":
                shard_urls: list[str] = []
                for child in root:
                    if self._tag(child.tag) != "sitemap":
                        continue
                    for node in child:
                        if self._tag(node.tag) == "loc" and node.text:
                            shard_urls.append(node.text.strip())
                for i in range(0, len(shard_urls), 10):
                    if len(articles) >= max_articles:
                        break
                    roots = await asyncio.gather(*[self._fetch_xml(client, u) for u in shard_urls[i:i + 10]])
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
                            articles[loc] = self._article_stub(loc, pub)
                            if len(articles) >= max_articles:
                                break
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
        try:
            resp = await fetch(client, self.url)
            for match in _SLUG_RE.finditer(resp.text):
                url = match.group(0).rstrip("\"'")
                if url not in articles and not self.should_skip_url(url):
                    articles[url] = self._article_stub(url)
                if len(articles) >= max_articles:
                    break
        except Exception as exc:
            logger.debug("[TheIsland] Homepage scrape failed: %s", exc)
        return list(articles.values())

    async def extract_content(self, url: str, client: httpx.AsyncClient) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
