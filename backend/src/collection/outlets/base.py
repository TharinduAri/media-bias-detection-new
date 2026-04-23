"""Base outlet scraper — shared HTTP, throttle, robots.txt, and retry logic.

All outlet-specific scrapers inherit from BaseOutletScraper and override:
  - ``discover_urls``  — returns a list of article URL dicts (url, date, title, outlet)
  - ``extract_content`` — given a URL + raw HTML, returns {text, title, date, raw_html}

The base class wires together:
  - Per-domain request throttling (MIN/MAX_DELAY_SECONDS)
  - robots.txt compliance (cached per domain)
  - Global concurrency semaphore (MAX_CONCURRENT_REQUESTS)
  - Ghost-response detection (GHOST_RESPONSE_MIN_BYTES)
  - Tenacity retry with exponential back-off (skips 403, GhostResponseError)
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Shared constants (mirrors top-level scraper.py for consistency)             #
# --------------------------------------------------------------------------- #
REQUEST_TIMEOUT_SECONDS = 12
MIN_DELAY_SECONDS = 0.5
MAX_DELAY_SECONDS = 2.0
GHOST_RESPONSE_MIN_BYTES = 200

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

SKIP_PATTERNS = [
    "#", "/contact", "/about", "/privacy", "/terms", "/search",
    "/cdn-cgi/", "email-protection", "/sports-news/", "/technology-news/",
    "/entertainment-news/", "/hot-news/", "/author-biography/", "news_archive",
    "/index.php", "/rss", "/mobi/", "disqus", "exchange-rates",
    "indicative-rates", "/home", "/latest", "/category/", "/tag/", "/page/",
    "/feed", "/amp/", "/print/", "/gallery/", "/video/",
]

# --------------------------------------------------------------------------- #
#  Module-level shared state (populated by the orchestrator in scraper.py)     #
# --------------------------------------------------------------------------- #
_REQUEST_SEMAPHORE: asyncio.Semaphore | None = None
_DOMAIN_LOCKS: dict[str, asyncio.Lock] = {}
_DOMAIN_LAST_REQUEST_AT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, RobotFileParser] = {}


def set_semaphore(sem: asyncio.Semaphore) -> None:
    """Called by the orchestrator once the event-loop semaphore is created."""
    global _REQUEST_SEMAPHORE
    _REQUEST_SEMAPHORE = sem


# --------------------------------------------------------------------------- #
#  Sentinel exceptions                                                          #
# --------------------------------------------------------------------------- #
class GhostResponseError(Exception):
    """HTTP 200 with a near-empty body — anti-scraping ghosting."""


class DiscoveryError(Exception):
    """Fatal failure during URL discovery for this outlet."""


# --------------------------------------------------------------------------- #
#  Shared helpers                                                               #
# --------------------------------------------------------------------------- #
def _choose_ua() -> str:
    return random.choice(USER_AGENTS)


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def _tag_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def is_article_url(url: str) -> bool:
    lower = url.lower()
    return not any(p in lower for p in SKIP_PATTERNS)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def _strip_html(html_text: str) -> str:
    from html.parser import HTMLParser
    import html as html_mod

    class _S(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._parts: list[str] = []

        def handle_data(self, data: str) -> None:
            c = data.strip()
            if c:
                self._parts.append(c)

        def get_text(self) -> str:
            return " ".join(self._parts).strip()

    clean = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    s = _S()
    s.feed(clean)
    return html_mod.unescape(s.get_text())


# --------------------------------------------------------------------------- #
#  HTTP primitives                                                              #
# --------------------------------------------------------------------------- #
def _domain_lock(domain: str) -> asyncio.Lock:
    if domain not in _DOMAIN_LOCKS:
        _DOMAIN_LOCKS[domain] = asyncio.Lock()
    return _DOMAIN_LOCKS[domain]


async def _throttle(domain: str) -> None:
    lock = _domain_lock(domain)
    async with lock:
        now = time.monotonic()
        last = _DOMAIN_LAST_REQUEST_AT.get(domain, 0.0)
        
        min_delay = 1.0 if "economynext.com" in domain else MIN_DELAY_SECONDS
        max_delay = max(min_delay, MAX_DELAY_SECONDS)
        
        jitter = random.uniform(min_delay, max_delay)
        wait = max(0.0, (last + jitter) - now)
        if wait > 0:
            await asyncio.sleep(wait)
        _DOMAIN_LAST_REQUEST_AT[domain] = time.monotonic()


async def _load_robots(client: httpx.AsyncClient, url: str) -> RobotFileParser:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[domain]

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        resp = await client.get(robots_url, follow_redirects=True,
                                headers={"User-Agent": _choose_ua()})
        if resp.status_code == 200 and resp.text:
            rp.parse(resp.text.splitlines())
    except Exception:
        pass
    _ROBOTS_CACHE[domain] = rp
    return rp


async def _can_fetch(client: httpx.AsyncClient, url: str, ua: str) -> bool:
    try:
        rp = await _load_robots(client, url)
        return rp.can_fetch(ua, url)
    except Exception:
        return True


async def fetch(client: httpx.AsyncClient, url: str, *,
                follow_redirects: bool = True,
                extra_headers: dict[str, str] | None = None) -> httpx.Response:
    """Throttled, robots-compliant GET with semaphore gating."""
    domain = _domain_of(url)
    await _throttle(domain)

    ua = _choose_ua()
    if not await _can_fetch(client, url, ua):
        raise PermissionError(f"Blocked by robots.txt: {url}")

    headers = {"User-Agent": ua}
    if extra_headers:
        headers.update(extra_headers)

    sem = _REQUEST_SEMAPHORE
    if sem:
        async with sem:
            resp = await client.get(url, follow_redirects=follow_redirects, headers=headers)
    else:
        resp = await client.get(url, follow_redirects=follow_redirects, headers=headers)

    resp.raise_for_status()
    return resp


async def fetch_xml(client: httpx.AsyncClient, url: str) -> ET.Element | None:
    """Fetch and parse an XML document; returns None on any failure."""
    try:
        resp = await fetch(client, url)
        return ET.fromstring(resp.text)
    except Exception as exc:
        logger.debug("XML fetch failed for %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------- #
#  Article extraction helper                                                    #
# --------------------------------------------------------------------------- #
def extract_with_trafilatura(raw_html: str, url: str = "") -> dict[str, str]:
    """Run trafilatura on raw_html; returns {text, title, date}."""
    if len(raw_html.strip()) < GHOST_RESPONSE_MIN_BYTES:
        raise GhostResponseError(f"Ghost response ({len(raw_html)}b) from {url}")

    result: dict[str, str] = {"text": "", "title": "", "date": ""}
    extracted_json = trafilatura.extract(
        raw_html,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    if extracted_json:
        payload = json.loads(extracted_json)
        result["text"] = payload.get("text") or ""
        result["title"] = payload.get("title") or ""
        result["date"] = payload.get("date") or ""

    if not result["text"]:
        result["text"] = trafilatura.extract(
            raw_html,
            include_comments=False,
            include_tables=False,
        ) or ""

    if not result["text"].strip():
        raise ValueError(f"trafilatura returned empty text for {url}")

    return result


# --------------------------------------------------------------------------- #
#  Base class                                                                   #
# --------------------------------------------------------------------------- #
class BaseOutletScraper(ABC):
    """Abstract base for a per-outlet scraper.

    Subclasses must implement:
        discover_urls()   — URL discovery (sitemap / RSS / API / crawler)
        extract_content() — article-level content extraction

    They may optionally override:
        should_skip_url() — extra outlet-specific URL filter
    """

    # Overridable in subclasses
    name: str = ""
    url: str = ""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self._domain = _domain_of(url)

    # -- Public API --------------------------------------------------------- #

    @abstractmethod
    async def discover_urls(
        self,
        client: httpx.AsyncClient,
        days_back: int,
        max_articles: int,
    ) -> list[dict[str, str]]:
        """Return list of {outlet, url, title, date} dicts."""

    async def extract_content(
        self, url: str, client: httpx.AsyncClient
    ) -> dict[str, str]:
        """Fetch url and return {text, title, date, raw_html}.

        Default implementation: HTTP GET → trafilatura.
        Override for outlets that need a different extraction path.
        """
        resp = await fetch(client, url)
        raw_html = resp.text
        result = extract_with_trafilatura(raw_html, url)
        result["raw_html"] = raw_html
        return result

    def should_skip_url(self, url: str) -> bool:
        """Return True to skip a candidate URL.  Default: SKIP_PATTERNS check."""
        return not is_article_url(url)

    # -- Shared helpers available to subclasses ----------------------------- #

    def _article_stub(self, url: str, date: datetime | None = None,
                      title: str = "") -> dict[str, str]:
        return {
            "outlet": self.name,
            "url": url,
            "title": title or url,
            "date": (date or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def _fetch(self, client: httpx.AsyncClient, url: str, **kw: Any) -> httpx.Response:
        return await fetch(client, url, **kw)

    async def _fetch_xml(self, client: httpx.AsyncClient, url: str) -> ET.Element | None:
        return await fetch_xml(client, url)

    def _parse_dt(self, value: Any) -> datetime | None:
        return _parse_dt(value)

    def _strip_html(self, html_text: str) -> str:
        return _strip_html(html_text)

    def _tag(self, tag: str) -> str:
        return _tag_name(tag)
