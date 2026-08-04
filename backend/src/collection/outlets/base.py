from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
import xml.etree.ElementTree as ET

from src.collection.core.utils import (
    is_article_url, domain_of, parse_metadata_datetime, strip_html, tag_name
)
from src.collection.core.http_client import (
    fetch, fetch_xml
)
from src.collection.core.extraction import extract_with_trafilatura

logger = logging.getLogger(__name__)


class BaseOutletScraper(ABC):
    """Abstract base for a per-outlet scraper.

    Subclasses must implement:
        discover_urls()   - URL discovery (sitemap / RSS / API)
        extract_content() - article-level content extraction

    They may optionally override:
        should_skip_url() - extra outlet-specific URL filter
    """

    name: str = ""
    url: str = ""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self._domain = domain_of(url)

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

        Default implementation: HTTP GET, then trafilatura.
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
        return parse_metadata_datetime(value)

    def _strip_html(self, html_text: str) -> str:
        return strip_html(html_text)

    def _tag(self, tag: str) -> str:
        return tag_name(tag)
