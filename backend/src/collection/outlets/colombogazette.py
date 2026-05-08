"""Colombo Gazette scraper (colombogazette.com).

WordPress-based online news portal.

Discovery:
  1. WordPress REST API (/wp-json/wp/v2/posts)
  2. WordPress sitemap index (/wp-sitemap.xml → posts-post shards)
  3. RSS feed (/feed)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_WP_API_PATH = "/wp-json/wp/v2/posts"
_WP_FIELDS = "id,date,title,link,content"
_WP_PER_PAGE = 100


class ColomboGazetteOutlet(BaseOutletScraper):
    """Colombo Gazette (colombogazette.com) — WordPress, WP API primary."""

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        api = await self._wp_api(client, days_back, max_articles)
        for a in api:
            articles[a["url"]] = a
        logger.info("[ColomboGazette] WP API: %d", len(articles))

        if len(articles) < max_articles:
            sm = await self._wp_sitemap(client, days_back, max_articles - len(articles))
            for a in sm:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        if len(articles) < max_articles:
            rss = await self._rss(client, days_back, max_articles - len(articles))
            for a in rss:
                if a["url"] not in articles:
                    articles[a["url"]] = a

        return list(articles.values())[:max_articles]

    async def _wp_api(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        endpoint = f"{self.url}{_WP_API_PATH}"
        articles: list[dict[str, str]] = []

        for page in range(1, 15):
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
                logger.debug("[ColomboGazette] WP API page %d failed: %s", page, exc)
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

    async def _wp_sitemap(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        index_root = await self._fetch_xml(client, f"{self.url}/wp-sitemap.xml")
        if index_root is None:
            return []

        shard_urls: list[str] = []
        if self._tag(index_root.tag) == "sitemapindex":
            for child in index_root:
                if self._tag(child.tag) != "sitemap":
                    continue
                for node in child:
                    if self._tag(node.tag) == "loc" and node.text:
                        loc = node.text.strip()
                        if "posts-post" in loc:
                            shard_urls.append(loc)

        articles: dict[str, dict[str, str]] = {}
        for i in range(0, len(shard_urls), 10):
            if len(articles) >= max_articles:
                break
            roots = await asyncio.gather(*[self._fetch_xml(client, u) for u in shard_urls[i:i + 10]])
            for root in roots:
                if root is None or self._tag(root.tag) != "urlset":
                    continue
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

        return list(articles.values())

    async def _rss(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        for path in ["/feed", "/rss", "/feed/rss2", "/?feed=rss2"]:
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

    async def extract_content(self, url: str, client: httpx.AsyncClient) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
