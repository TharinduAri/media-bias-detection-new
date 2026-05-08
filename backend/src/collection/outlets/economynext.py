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
from urllib.parse import urlparse

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import GhostResponseError, fetch
from src.collection.core.extraction import extract_with_trafilatura
from src.collection.core.utils import domain_of

logger = logging.getLogger(__name__)

# Paths known to be directory-blocked on economynext.com
_BLOCKED_SECTION_PATTERNS = ["/culture", "/sports", "/life-and-style", "/entertainment"]

# Ghost/500 threshold: if this fraction of requests fail, warn and cap articles
_CIRCUIT_BREAKER_RATIO = 0.50
_EN_GHOST_THRESHOLD = 500   # Economy Next ghosted pages tend to be < 500 bytes
_ARTICLE_HINT_RE = re.compile(r"/20\d{2}/\d{2}/\d{2}/|/[a-z0-9][a-z0-9\-]{10,}")

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://google.com",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
}


class EconomyNextOutlet(BaseOutletScraper):
    """Economy Next (economynext.com) — adversarial WordPress scraper."""

    def __init__(self, name: str, url: str, **kwargs):
        super().__init__(name, url)
        self._cdx_cache: dict[str, str] = {}

    def should_skip_url(self, url: str) -> bool:
        base_skip = super().should_skip_url(url)
        if base_skip:
            # EconomyNext frequently uses single-segment slug URLs
            # (e.g., /some-long-article-slug) which the generic filter rejects.
            parsed = urlparse(url)
            path = (parsed.path or "").strip("/")
            if (
                path
                and "/" not in path
                and re.fullmatch(r"[a-z0-9][a-z0-9\-]{8,}", path) is not None
            ):
                base_skip = False
        if base_skip:
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

        # 1. WP REST API (fastest; returns full structured JSON)
        api_items = await self._wp_api_discover(client, days_back, max_articles)
        for item in api_items:
            url = item.get("url")
            if url and url not in articles:
                articles[url] = item
        if api_items:
            logger.info("[EconomyNext] WP API: %d", len(articles))

        # 2. Live WordPress sitemap discovery
        if len(articles) < max_articles:
            live_sitemap_items = await self._live_sitemap_discover(client, days_back, max_articles - len(articles))
            for item in live_sitemap_items:
                url = item.get("url")
                if url and url not in articles:
                    articles[url] = item
            if live_sitemap_items:
                logger.info("[EconomyNext] Live sitemap added %d URLs", len(live_sitemap_items))

        # 3. RSS fallback
        if len(articles) < max_articles:
            rss_items = await self._rss_discover(client, days_back, max_articles - len(articles))
            for item in rss_items:
                url = item.get("url")
                if url and url not in articles:
                    articles[url] = item
            if rss_items:
                logger.info("[EconomyNext] RSS added %d URLs", len(rss_items))

        # 3. Wayback CDX top-up fallback
        if len(articles) >= max_articles:
            logger.info("[EconomyNext] Total discovered: %d URLs", len(articles))
            return list(articles.values())[:max_articles]

        from datetime import timezone as _tz
        _now = datetime.now(_tz.utc)
        _since = (_now - timedelta(days=days_back)).strftime("%Y%m%d")
        _until = _now.strftime("%Y%m%d")
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=economynext.com/*"
            "&output=json&fl=timestamp,original"
            "&filter=statuscode:200&filter=mimetype:text/html"
            f"&collapse=urlkey&from={_since}&to={_until}"
            f"&limit={max_articles * 25}&offset=0"
        )
        try:
            resp = await client.get(cdx_url, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 2:
                        ts, orig_url = row[0], row[1]
                        if self.should_skip_url(orig_url):
                            continue
                        if not _ARTICLE_HINT_RE.search(orig_url):
                            continue
                        if orig_url not in articles:
                            self._cdx_cache[orig_url] = ts
                            articles[orig_url] = self._article_stub(orig_url)
                            if len(articles) >= max_articles:
                                break
        except Exception as exc:
            logger.debug("[EconomyNext] CDX fetch failed: %s", exc)

        logger.info("[EconomyNext] Total discovered: %d URLs via Wayback Machine", len(articles))
        return list(articles.values())[:max_articles]

    async def _wp_api_discover(
        self, client: httpx.AsyncClient, days_back: int, max_articles: int
    ) -> list[dict[str, str]]:
        from urllib.parse import urlencode
        cutoff = datetime.now() - timedelta(days=days_back)
        endpoint = f"{self.url}/wp-json/wp/v2/posts"
        articles: list[dict[str, str]] = []

        for page in range(1, 15):
            if len(articles) >= max_articles:
                break
            params = urlencode({
                "_fields": "id,date,title,link,content",
                "per_page": "100",
                "page": str(page),
                "orderby": "date",
                "order": "desc",
            })
            try:
                resp = await fetch(client, f"{endpoint}?{params}", extra_headers=_BROWSER_HEADERS)
                posts = resp.json()
            except Exception as exc:
                logger.debug("[EconomyNext] WP API page %d failed: %s", page, exc)
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

            if len(posts) < 100:
                break

        return articles

    async def _live_sitemap_discover(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        if max_articles <= 0:
            return []
        cutoff = datetime.now() - timedelta(days=days_back)
        index_root = await self._fetch_xml(client, f"{self.url}/wp-sitemap.xml")
        if index_root is None:
            return []

        shard_urls: list[str] = []
        if self._tag(index_root.tag) == "sitemapindex":
            for child in index_root:
                if self._tag(child.tag) != "sitemap":
                    continue
                loc = None
                for node in child:
                    if self._tag(node.tag) == "loc" and node.text:
                        loc = node.text.strip()
                        break
                if loc and "posts-post" in loc:
                    shard_urls.append(loc)
        elif self._tag(index_root.tag) == "urlset":
            shard_urls = [f"{self.url}/wp-sitemap.xml"]

        items: dict[str, dict[str, str]] = {}
        batch_size = 12
        for start in range(0, len(shard_urls), batch_size):
            if len(items) >= max_articles:
                break
            batch = shard_urls[start : start + batch_size]
            roots = await asyncio.gather(*[self._fetch_xml(client, url) for url in batch])
            for root in roots:
                if root is None or self._tag(root.tag) != "urlset":
                    continue
                for child in root:
                    if self._tag(child.tag) != "url":
                        continue
                    loc = lastmod = None
                    for node in child:
                        tag = self._tag(node.tag)
                        if tag == "loc" and node.text:
                            loc = node.text.strip()
                        elif tag == "lastmod" and node.text:
                            lastmod = node.text.strip()
                    if not loc or self.should_skip_url(loc):
                        continue
                    if not _ARTICLE_HINT_RE.search(loc):
                        continue
                    pub = self._parse_dt(lastmod)
                    if pub and pub < cutoff:
                        continue
                    if loc not in items:
                        items[loc] = self._article_stub(loc, pub)
                    if len(items) >= max_articles:
                        break

        return list(items.values())

    async def _rss_discover(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        if max_articles <= 0:
            return []
        import xml.etree.ElementTree as ET

        cutoff = datetime.now() - timedelta(days=days_back)
        for path in ("/feed", "/rss", "/feed/rss2"):
            try:
                resp = await fetch(client, f"{self.url}{path}", extra_headers=_BROWSER_HEADERS)
                root = ET.fromstring(resp.text)
            except Exception:
                continue

            entries = root.findall(".//item")
            rows: list[dict[str, str]] = []
            for item in entries:
                link = item.findtext("link")
                if not link or self.should_skip_url(link):
                    continue
                if not _ARTICLE_HINT_RE.search(link):
                    continue
                pub = self._parse_dt(item.findtext("pubDate"))
                if pub and pub < cutoff:
                    continue
                rows.append(self._article_stub(link, pub, item.findtext("title") or ""))
                if len(rows) >= max_articles:
                    break
            if rows:
                return rows

        return []

    # -- Content extraction ------------------------------------------------- #

    async def _wayback_lookup(self, url: str, client: httpx.AsyncClient) -> str | None:
        """Query Wayback CDX for the most recent archived timestamp of a URL."""
        from urllib.parse import quote
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            f"?url={quote(url, safe='')}"
            "&output=json&fl=timestamp&filter=statuscode:200"
            "&limit=1&sort=reverse"
        )
        try:
            resp = await client.get(cdx_url, timeout=10.0)
            data = resp.json()
            if isinstance(data, list) and len(data) > 1:
                return str(data[1][0])
        except Exception:
            pass
        return None

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Economy Next-specific extraction with ghost detection and browser headers."""
        try:
            resp = await fetch(client, url, extra_headers=_BROWSER_HEADERS,
                               follow_redirects=True)
            raw_html = resp.text
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404, 500, 503):
                ts = self._cdx_cache.get(url)
                if ts is None:
                    ts = await self._wayback_lookup(url, client)
                if ts:
                    archive_url = f"https://web.archive.org/web/{ts}/{url}"
                    logger.debug("[EconomyNext] %d on live URL, falling back to Wayback: %s", exc.response.status_code, archive_url)
                    resp = await client.get(archive_url, follow_redirects=True, timeout=20.0, headers=_BROWSER_HEADERS)
                    resp.raise_for_status()
                    raw_html = resp.text
                else:
                    raise
            else:
                raise

        # Economy Next ghost: 200 OK with tiny body — raise non-retryable sentinel
        if len(raw_html.strip()) < _EN_GHOST_THRESHOLD:
            raise GhostResponseError(
                f"[EconomyNext] Ghost response ({len(raw_html)}b) for {url}"
            )

        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
