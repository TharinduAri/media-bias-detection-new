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

from .base import BaseOutletScraper
from src.collection.core.http_client import fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

# Article URL patterns for Newsfirst
# Matches: /2024/04/23/some-slug/ or /?p=123456
_ARTICLE_URL_RE = re.compile(
    r"https?://[^/]*newsfirst\.lk/"
    r"(?:\d{4}/\d{2}/\d{2}/[a-z0-9\-]+/?|(?:\?p=\d+))"
)

_RSS_CANDIDATES = ["/feed/rss2", "/feed", "/rss", "/?feed=rss2"]
_CATEGORY_PATHS = [
    "/latest",
    "/news/local/",
    "/news/world/",
    "/news/business/",
    "/news/politics/",
    "/news/sports/",
]
_SITEMAP_CANDIDATES = ["/wp-sitemap.xml", "/sitemap.xml"]


class NewsfirstOutlet(BaseOutletScraper):
    """Newsfirst English — RSS-primary, homepage link-scraping fallback.

    Does NOT use focused_crawler (permanent spider timeout for JS-rendered sites).
    """

    def __init__(self, name: str, url: str, **kwargs):
        super().__init__(name, url)
        self._cdx_cache: dict[str, str] = {}

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}

        # 1. RSS Feed Discovery
        for candidate in _RSS_CANDIDATES:
            if len(articles) >= max_articles: break
            try:
                rss_url = f"{self.url.rstrip('/')}{candidate}"
                resp = await fetch(client, rss_url)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.text)
                from datetime import timezone as _tz
                _cutoff = datetime.now(_tz.utc) - timedelta(days=days_back)
                
                count_before = len(articles)
                for item in root.findall(".//item"):
                    link = item.findtext("link")
                    if not link or self.should_skip_url(link):
                        continue
                    pub_raw = item.findtext("pubDate")
                    pub = self._parse_dt(pub_raw)
                    if pub:
                        if pub.tzinfo is None:
                            pub = pub.replace(tzinfo=_tz.utc)
                        if pub < _cutoff:
                            continue
                    if link not in articles:
                        articles[link] = self._article_stub(link, pub)
                    if len(articles) >= max_articles:
                        break
                
                if len(articles) > count_before:
                    logger.info("[Newsfirst] Discovered %d URLs via RSS feed: %s", len(articles) - count_before, rss_url)
                    # Don't break, try to get more if needed, but RSS is usually limited
            except Exception as exc:
                logger.debug("[Newsfirst] RSS candidate %s failed: %s", candidate, exc)

        # 2. Sitemap traversal (best coverage when RSS is sparse/blocked)
        if len(articles) < max_articles:
            sitemap_items = await self._sitemap_discover(client, days_back, max_articles - len(articles))
            for item in sitemap_items:
                url = item.get("url")
                if url and url not in articles:
                    articles[url] = item
            if sitemap_items:
                logger.info("[Newsfirst] Sitemap added %d URLs", len(sitemap_items))

        # 3. Latest Page & Category listing pages (Fallback)
        if len(articles) < max_articles:
            for path in _CATEGORY_PATHS:
                if len(articles) >= max_articles:
                    break
                try:
                    target_url = f"{self.url.rstrip('/')}{path}"
                    resp = await fetch(client, target_url)
                    html = resp.text
                    import bs4
                    soup = bs4.BeautifulSoup(html, "html.parser")
                    
                    # New Angular-based structure: a[href^="/20"]
                    # Legacy structure: .news-block-one etc.
                    links = soup.select('a[href^="/20"], .news-block-one a[href], .news-block-two a[href]')
                    
                    for a_tag in links:
                        href = a_tag.get("href")
                        if not href:
                            continue
                            
                        from urllib.parse import urljoin
                        candidate = urljoin(target_url, href)
                        
                        if _ARTICLE_URL_RE.match(candidate):
                            if candidate not in articles and not self.should_skip_url(candidate):
                                # Try to find date in inner div (DD-MM-YYYY)
                                pub_date = None
                                date_div = a_tag.find("div", string=re.compile(r'\d{2}-\d{2}-\d{4}'))
                                if date_div:
                                    pub_date = self._parse_dt(date_div.text.strip())
                                
                                articles[candidate] = self._article_stub(candidate, pub_date)
                                
                    # Also try the regex as an ultimate fallback on the page HTML
                    for match in _ARTICLE_URL_RE.finditer(html):
                        candidate = match.group(0).rstrip('"\'')
                        if candidate not in articles and not self.should_skip_url(candidate):
                            articles[candidate] = self._article_stub(candidate)
                            
                except Exception as exc:
                    logger.debug("[Newsfirst] Page scrape %s failed: %s", path, exc)

            logger.info("[Newsfirst] Discovered %d URLs total after category scrape", len(articles))

        # 4. Wayback CDX API
        if len(articles) < max_articles:
            from datetime import timezone as _tz
            _now = datetime.now(_tz.utc)
            _since = (_now - timedelta(days=days_back)).strftime("%Y%m%d")
            _until = _now.strftime("%Y%m%d")
            cdx_url = (
                "https://web.archive.org/cdx/search/cdx"
                "?url=english.newsfirst.lk/*"
                "&output=json&fl=timestamp,original"
                "&filter=statuscode:200&filter=mimetype:text/html"
                f"&collapse=urlkey&from={_since}&to={_until}"
                f"&limit={max_articles * 20}&offset=0"
            )
            try:
                resp = await client.get(cdx_url, timeout=20.0)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and len(data) > 1:
                    for row in data[1:]:
                        if len(row) >= 2:
                            ts, orig_url = row[0], row[1]
                            if re.search(r'english\.newsfirst\.lk/20\d\d/\d\d/\d\d/', orig_url):
                                if orig_url not in articles and not self.should_skip_url(orig_url):
                                    self._cdx_cache[orig_url] = ts
                                    articles[orig_url] = self._article_stub(orig_url)
                                    if len(articles) >= max_articles:
                                        break
            except Exception as exc:
                logger.debug("[Newsfirst] CDX fetch failed: %s", exc)

        logger.info("[Newsfirst] Total discovered: %d URLs", len(articles))
        return list(articles.values())[:max_articles]

    async def _sitemap_discover(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        if max_articles <= 0:
            return []

        from datetime import timezone as _tz
        cutoff = datetime.now(_tz.utc) - timedelta(days=days_back)
        article_map: dict[str, dict[str, str]] = {}

        index_urls: list[str] = [f"{self.url.rstrip('/')}{path}" for path in _SITEMAP_CANDIDATES]
        shard_urls: list[str] = []

        for index_url in index_urls:
            root = await self._fetch_xml(client, index_url)
            if root is None:
                continue
            tag = self._tag(root.tag)
            if tag == "sitemapindex":
                for child in root:
                    if self._tag(child.tag) != "sitemap":
                        continue
                    loc = lastmod = None
                    for node in child:
                        node_tag = self._tag(node.tag)
                        if node_tag == "loc" and node.text:
                            loc = node.text.strip()
                        elif node_tag == "lastmod" and node.text:
                            lastmod = node.text.strip()
                    pub = self._parse_dt(lastmod)
                    if pub is not None:
                        if pub.tzinfo is None:
                            pub = pub.replace(tzinfo=_tz.utc)
                        if pub < cutoff:
                            continue
                    if loc and "newsfirst.lk" in loc:
                        shard_urls.append(loc)
            elif tag == "urlset":
                shard_urls.append(index_url)

        # De-duplicate while preserving order
        deduped_shards: list[str] = []
        seen_shards: set[str] = set()
        for url in shard_urls:
            if url not in seen_shards:
                seen_shards.add(url)
                deduped_shards.append(url)

        for shard in deduped_shards:
            if len(article_map) >= max_articles:
                break
            root = await self._fetch_xml(client, shard)
            if root is None or self._tag(root.tag) != "urlset":
                continue
            for child in root:
                if self._tag(child.tag) != "url":
                    continue
                loc = lastmod = None
                for node in child:
                    node_tag = self._tag(node.tag)
                    if node_tag == "loc" and node.text:
                        loc = node.text.strip()
                    elif node_tag == "lastmod" and node.text:
                        lastmod = node.text.strip()
                if not loc or self.should_skip_url(loc):
                    continue
                if not _ARTICLE_URL_RE.match(loc):
                    continue
                pub = self._parse_dt(lastmod)
                if pub is not None:
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=_tz.utc)
                    if pub < cutoff:
                        continue
                if loc not in article_map:
                    article_map[loc] = self._article_stub(loc, pub)
                if len(article_map) >= max_articles:
                    break

        return list(article_map.values())

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
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            resp = await client.get(url, follow_redirects=True, timeout=20.0, headers=headers)
            resp.raise_for_status()
            raw_html = resp.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (404, 500, 503):
                ts = self._cdx_cache.get(url)
                if ts is None:
                    ts = await self._wayback_lookup(url, client)
                if ts:
                    archive_url = f"https://web.archive.org/web/{ts}/{url}"
                    logger.debug("[Newsfirst] HTTP %d on live URL, falling back to Wayback: %s", status, archive_url)
                    resp = await client.get(archive_url, follow_redirects=True, timeout=20.0, headers=headers)
                    resp.raise_for_status()
                    raw_html = resp.text
                else:
                    raise
            else:
                raise

        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
