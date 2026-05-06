"""Lanka Business Online (LBO) scraper.

Discovery strategy:
  1. WordPress REST API (/wp-json/wp/v2/posts) — primary; returns structured JSON
     with full content, title, date — no need for HTML extraction at all.
  2. WordPress sitemap index (/wp-sitemap.xml → /wp-sitemap-posts-post-N.xml)
     Concurrent shard fetching (21 shards observed in audit); used as fallback
     when the REST API is rate-limited or unavailable.

Content extraction:
  - WP REST API path: strip HTML from `content.rendered` field using _strip_html()
  - Sitemap fallback path: standard trafilatura extraction
  - Both paths skip the HTTP round-trip for ghost detection (API returns structured data)

Known info from audit:
  - WordPress CMS: sitemap traversal resolved up to 21 individual shards
  - /wp-json/wp/v2/posts is publicly accessible (no auth required)
  - API responses include full article content — far more reliable than scraping
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import GhostResponseError, fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_WP_API_PATH = "/wp-json/wp/v2/posts"
_WP_API_FIELDS = "id,date,title,link,content"
_WP_API_PER_PAGE = 100   # Max allowed by WP REST API
_WP_API_MAX_PAGES = 12

_TRUNCATION_MARKERS = (
    "[…]", "[...]", "[&hellip;]", "…", "...", "continue reading", "read more",
)


class LBOOutlet(BaseOutletScraper):
    """Lanka Business Online (lbo.lk / lankabusinessonline.com) — WP API primary."""

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        # Primary: WordPress REST API
        api_articles = await self._wp_api_discover(client, days_back, max_articles)
        for art in api_articles:
            articles[art["url"]] = art
        logger.info("[LBO] WP API: %d articles", len(articles))

        # Fallback: sitemap shards if API yield is low
        if len(articles) < max_articles:
            sitemap_articles = await self._wp_sitemap_discover(
                client, days_back, max_articles - len(articles)
            )
            for art in sitemap_articles:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            if sitemap_articles:
                logger.info("[LBO] Sitemap fallback added %d articles", len(sitemap_articles))

        return list(articles.values())[:max_articles]

    # -- WordPress REST API ------------------------------------------------- #

    async def _wp_api_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        cutoff = datetime.now() - timedelta(days=days_back)
        endpoint = f"{self.url}{_WP_API_PATH}"
        articles: list[dict[str, str]] = []
        max_pages = _WP_API_MAX_PAGES

        for page in range(1, max_pages + 1):
            if len(articles) >= max_articles:
                break
            params = {
                "_fields": _WP_API_FIELDS,
                "per_page": str(_WP_API_PER_PAGE),
                "page": str(page),
                "orderby": "date",
                "order": "desc",
            }
            try:
                resp = await fetch(client, f"{endpoint}?{urlencode(params)}")
                posts = resp.json()
                if page == 1:
                    header_pages = resp.headers.get("X-WP-TotalPages")
                    if header_pages and header_pages.isdigit():
                        max_pages = min(max_pages, max(1, int(header_pages)))
            except Exception as exc:
                logger.debug("[LBO] WP API page %d failed: %s", page, exc)
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

                # Pre-extract content from the API response itself
                content_obj = post.get("content")
                title_obj = post.get("title")
                raw_html = content_obj.get("rendered", "") if isinstance(content_obj, dict) else ""
                title_html = title_obj.get("rendered", "") if isinstance(title_obj, dict) else ""
                text = self._strip_html(raw_html)
                title = self._strip_html(title_html)

                stub = self._article_stub(url, pub, title)
                if text and len(text) >= 50 and not self._looks_truncated(text):
                    # We already have the full content — embed it in the stub
                    stub["text"] = text
                    stub["raw_html"] = raw_html

                articles.append(stub)
                if len(articles) >= max_articles:
                    break

            if len(posts) < _WP_API_PER_PAGE:
                break  # Last page

        return articles

    def _looks_truncated(self, text: str) -> bool:
        lower = text.strip().lower()
        return any(lower.endswith(m) for m in _TRUNCATION_MARKERS)

    # -- WordPress sitemap fallback ----------------------------------------- #

    async def _wp_sitemap_discover(
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
        elif self._tag(index_root.tag) == "urlset":
            shard_urls = [f"{self.url}/wp-sitemap.xml"]

        articles: dict[str, dict[str, str]] = {}
        batch_size = 20
        for i in range(0, len(shard_urls), batch_size):
            if len(articles) >= max_articles:
                break
            batch = shard_urls[i:i + batch_size]
            roots = await asyncio.gather(*[self._fetch_xml(client, u) for u in batch])
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

    # -- Content extraction ------------------------------------------------- #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Try WP REST API by slug first; fall back to trafilatura HTML scraping."""
        # Attempt API extraction by slug
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        if slug and not slug.isdigit():
            api_result = await self._api_extract_by_slug(url, slug, client)
            if api_result:
                return api_result

        # HTML fallback
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result

    async def _api_extract_by_slug(
        self, url: str, slug: str, client: httpx.AsyncClient
    ) -> dict[str, str] | None:
        endpoint = f"{self.url}{_WP_API_PATH}"
        params = urlencode({"slug": slug, "_fields": _WP_API_FIELDS, "per_page": "1"})
        try:
            resp = await fetch(client, f"{endpoint}?{params}")
            posts = resp.json()
        except Exception:
            return None

        if not isinstance(posts, list) or not posts:
            return None
        post = posts[0]
        if not isinstance(post, dict):
            return None

        content_obj = post.get("content")
        title_obj = post.get("title")
        raw_html = content_obj.get("rendered", "") if isinstance(content_obj, dict) else ""
        title_html = title_obj.get("rendered", "") if isinstance(title_obj, dict) else ""
        text = self._strip_html(raw_html)
        title = self._strip_html(title_html)

        if not text or len(text) < 50 or self._looks_truncated(text):
            return None

        pub = self._parse_dt(post.get("date"))
        return {
            "text": text,
            "raw_html": raw_html,
            "title": title,
            "date": (pub or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        }

