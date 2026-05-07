"""Daily FT scraper.

Discovery strategy:
  1. Custom sitemap endpoint: /sitemaps/english-{page} (0-indexed, paginated)
     Each page is a plain urlset XML containing up to 300 article URLs.
     Traverse pages until fewer than 300 URLs returned (end of pagination).
  2. RSS feed fallback: /feed

Content extraction: standard trafilatura (Daily FT HTML is clean and well-structured).

Known info from audit:
  - /sitemaps/english-0 resolved 300 article URLs successfully
  - No ghost responses or 403 issues observed
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from .base import BaseOutletScraper
from src.collection.core.http_client import fetch
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)

_SITEMAP_PAGE_SIZE = 300       # Daily FT returns exactly this many per page
_MAX_SITEMAP_PAGES = 20        # Safety cap: 20 × 300 = 6,000 URLs max
_PROBE_STEP = 5000
_FALLBACK_IDX = 320000
_STATE_FILE = Path(__file__).parent.parent.parent.parent / "data" / "dailyft_state.json"


def _load_state() -> int:
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text())
            return int(data.get("latest_idx", _FALLBACK_IDX))
    except Exception:
        pass
    return _FALLBACK_IDX


def _save_state(latest_idx: int) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"latest_idx": latest_idx, "updated": datetime.now().isoformat()})
        )
    except Exception:
        pass


class DailyFTOutlet(BaseOutletScraper):
    """Daily FT (ft.lk) — paginated /sitemaps/english-N discovery."""

    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        articles: dict[str, dict[str, str]] = {}
        cutoff = datetime.now() - timedelta(days=days_back)

        # 1. Discovery via Home Page (fastest for very recent articles)
        try:
            resp = await fetch(client, self.url)
            import re
            # Extract URLs like .../category/title/id-number
            # IDs are usually at the end after a dash
            urls = re.findall(r'href="(https://www\.ft\.lk/[^"]+-\d+)"', resp.text)
            for url in urls:
                if self.should_skip_url(url):
                    continue
                # We don't have dates from the home page easily, but we'll get them during extraction
                # or just use 'now' as a stub if we have to.
                articles[url] = self._article_stub(url)
        except Exception as e:
            logger.warning("[DailyFT] Home page discovery failed: %s", e)

        # 2. Discovery via Sitemap (robust for catching up)
        # Load the last known good sitemap index from state file to avoid probing from scratch.
        latest_idx = _load_state()

        # Verify the stored index is still valid; if not, search backward for the real latest.
        try:
            verify_resp = await client.head(
                f"{self.url}/sitemaps/english-{latest_idx}", timeout=5.0
            )
            if verify_resp.status_code != 200:
                logger.warning("[DailyFT] Stored sitemap index %d returned %d, searching backward", latest_idx, verify_resp.status_code)
                found = 0
                for probe_idx in range(latest_idx - _PROBE_STEP, max(0, latest_idx - 20 * _PROBE_STEP), -_PROBE_STEP):
                    try:
                        r = await client.head(f"{self.url}/sitemaps/english-{probe_idx}", timeout=5.0)
                        if r.status_code == 200:
                            found = probe_idx
                            break
                    except Exception:
                        continue
                latest_idx = found if found else _FALLBACK_IDX
                logger.info("[DailyFT] Backward search found sitemap index: %d", latest_idx)
        except Exception:
            pass

        # Probe forward from the verified index to find the current ceiling.
        for probe_idx in range(latest_idx, latest_idx + 20 * _PROBE_STEP, _PROBE_STEP):
            try:
                probe_resp = await client.head(f"{self.url}/sitemaps/english-{probe_idx}", timeout=5.0)
                if probe_resp.status_code == 200:
                    latest_idx = probe_idx
                else:
                    break
            except Exception:
                break

        _save_state(latest_idx)
        logger.info("[DailyFT] Using sitemap ceiling index: %d", latest_idx)
        
        # Now crawl backwards from latest_idx
        pages_to_crawl = []
        for i in range(0, 5): # Check last 5 sitemap chunks (approx 5000 articles)
            idx = latest_idx - (i * 1000)
            if idx >= 0:
                pages_to_crawl.append(f"{self.url}/sitemaps/english-{idx}")

        logger.info("[DailyFT] Crawling sitemap pages: %s", pages_to_crawl)
        roots = await asyncio.gather(
            *[self._fetch_xml(client, url) for url in pages_to_crawl]
        )

        for root in roots:
            if root is None or self._tag(root.tag) != "urlset":
                continue

            for child in root:
                if self._tag(child.tag) != "url":
                    continue
                
                loc = None
                pub_date = None
                
                # Check for <loc> and <news:news><news:publication_date>
                for node in child:
                    t = self._tag(node.tag)
                    if t == "loc" and node.text:
                        loc = node.text.strip()
                    elif t == "news":
                        # Parse news:publication_date
                        for news_node in node:
                            if self._tag(news_node.tag) == "publication_date" and news_node.text:
                                pub_date = self._parse_dt(news_node.text.strip())
                
                if not loc or self.should_skip_url(loc):
                    continue
                
                if pub_date and pub_date < cutoff:
                    continue
                
                # If we already got it from home page, this will update it with a better date
                articles[loc] = self._article_stub(loc, pub_date)
                if len(articles) >= max_articles * 2: # Get plenty then trim
                    break

        logger.info("[DailyFT] Discovered %d article URLs total", len(articles))
        return list(articles.values())[:max_articles]

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        resp = await fetch(client, url, follow_redirects=True)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result
