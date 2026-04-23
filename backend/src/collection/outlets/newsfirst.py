"""Newsfirst scraper.

Newsfirst (english.newsfirst.lk) is the most structurally resistant outlet.

Why the general crawler always fails:
  - The site uses JavaScript-heavy rendering (React/Vue SPA)
  - The focused_crawler (trafilatura's spider) never resolves article links
    because they are injected client-side after page load
  - A 60s crawler timeout is consumed and yields 0 URLs every run

Approach — skip the crawler entirely and use structured data sources only:
  1. RSS feed: /feed or /rss (most likely to work; Newsfirst has a public RSS)
  2. JSON-LD sitemaps or sitemap.xml if accessible
  3. Direct category page link-scraping (fallback): fetch the homepage HTML
     and extract all hrefs that match the article URL pattern
     (/YYYY/MM/DD/ or /?p=NNNNN canonical form)

Content extraction:
  - Newsfirst uses a clean Elementor/WordPress theme — trafilatura extracts well
  - No ghost responses observed (only discovery failure)
  - Timeout guard: 30s per fetch (site can be slow)

Note: If all three strategies return 0 URLs, log a CRITICAL and return empty
rather than burning a 60s crawler timeout on a known-dead path.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx

from .base import BaseOutletScraper, fetch, extract_with_trafilatura

logger = logging.getLogger(__name__)

# Article URL patterns for Newsfirst
# Matches: /2024/04/23/some-slug/ or /?p=123456
_ARTICLE_URL_RE = re.compile(
    r"https?://[^/]*newsfirst\.lk/"
    r"(?:\d{4}/\d{2}/\d{2}/[a-z0-9\-]+/?|(?:\?p=\d+))"
)

_RSS_CANDIDATES = ["/feed", "/rss", "/feed/rss2", "/?feed=rss2"]
_CATEGORY_PATHS = ["/", "/news/local/", "/news/world/", "/news/business/"]


class NewsfirstOutlet(BaseOutletScraper):
    """Newsfirst English — RSS-primary, homepage link-scraping fallback.

    Does NOT use focused_crawler (permanent spider timeout for JS-rendered sites).
    """

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        cutoff = datetime.now() - timedelta(days=days_back)

        # 1. RSS feeds
        for path in _RSS_CANDIDATES:
            if len(articles) >= max_articles:
                break
            rss_urls = await self._try_rss(client, f"{self.url}{path}", cutoff, max_articles)
            for art in rss_urls:
                articles[art["url"]] = art
            if rss_urls:
                logger.info("[Newsfirst] RSS %s yielded %d URLs", path, len(rss_urls))
                break  # Use first working RSS feed

        # 2. Standard sitemap.xml attempt (might work if WP sitemap is enabled)
        if len(articles) < max(20, max_articles // 4):
            sitemap_urls = await self._try_sitemap(client, cutoff, max_articles)
            for art in sitemap_urls:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            if sitemap_urls:
                logger.info("[Newsfirst] Sitemap yielded %d URLs", len(sitemap_urls))

        # 3. Homepage link-scraping fallback
        if len(articles) < max(10, max_articles // 8):
            link_urls = await self._homepage_link_scrape(client, cutoff, max_articles)
            for art in link_urls:
                if art["url"] not in articles:
                    articles[art["url"]] = art
            if link_urls:
                logger.info("[Newsfirst] Homepage scrape yielded %d URLs", len(link_urls))

        if not articles:
            logger.warning(
                "[Newsfirst] All discovery strategies returned 0 URLs. "
                "Site may be fully blocking automated access."
            )
        else:
            logger.info("[Newsfirst] Total discovered: %d URLs", len(articles))

        return list(articles.values())[:max_articles]

    # -- RSS ---------------------------------------------------------------- #

    async def _try_rss(
        self,
        client: httpx.AsyncClient,
        rss_url: str,
        cutoff: datetime,
        max_articles: int,
    ) -> list[dict[str, str]]:
        import xml.etree.ElementTree as ET
        try:
            resp = await fetch(client, rss_url)
            root = ET.fromstring(resp.text)
        except Exception as exc:
            logger.debug("[Newsfirst] RSS %s unavailable: %s", rss_url, exc)
            return []

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

        return items

    # -- Sitemap ------------------------------------------------------------ #

    async def _try_sitemap(
        self, client: httpx.AsyncClient, cutoff: datetime, max_articles: int
    ) -> list[dict[str, str]]:
        root = await self._fetch_xml(client, f"{self.url}/wp-sitemap.xml")
        if root is None:
            root = await self._fetch_xml(client, f"{self.url}/sitemap.xml")
        if root is None:
            return []

        urls: dict[str, dict[str, str]] = {}
        tag = self._tag(root.tag)
        if tag == "sitemapindex":
            # Only follow post shards, not taxonomy/etc.
            import asyncio
            shard_urls = []
            for child in root:
                if self._tag(child.tag) != "sitemap":
                    continue
                for node in child:
                    if self._tag(node.tag) == "loc" and node.text:
                        loc = node.text.strip()
                        if "posts-post" in loc or "post-sitemap" in loc:
                            shard_urls.append(loc)
            shard_roots = await asyncio.gather(
                *[self._fetch_xml(client, u) for u in shard_urls[:10]]
            )
            for shard in shard_roots:
                if shard is None or self._tag(shard.tag) != "urlset":
                    continue
                self._parse_urlset(shard, cutoff, urls, max_articles)
        elif tag == "urlset":
            self._parse_urlset(root, cutoff, urls, max_articles)

        return list(urls.values())

    def _parse_urlset(
        self, root: object, cutoff: datetime,
        urls: dict[str, dict[str, str]], max_articles: int
    ) -> None:
        import xml.etree.ElementTree as ET
        assert isinstance(root, ET.Element)
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

    # -- Homepage link-scraping fallback ------------------------------------ #

    async def _homepage_link_scrape(
        self, client: httpx.AsyncClient, cutoff: datetime, max_articles: int
    ) -> list[dict[str, str]]:
        urls: dict[str, dict[str, str]] = {}
        for path in _CATEGORY_PATHS:
            if len(urls) >= max_articles:
                break
            try:
                resp = await fetch(client, f"{self.url}{path}")
                html = resp.text
            except Exception as exc:
                logger.debug("[Newsfirst] Link-scrape %s failed: %s", path, exc)
                continue

            for match in _ARTICLE_URL_RE.finditer(html):
                candidate = match.group(0).rstrip('"\'')
                if candidate in urls or self.should_skip_url(candidate):
                    continue
                urls[candidate] = self._article_stub(candidate)
                if len(urls) >= max_articles:
                    break

        return list(urls.values())

    # -- Content extraction ------------------------------------------------- #

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
