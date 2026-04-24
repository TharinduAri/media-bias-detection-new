import html
import random
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

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
    '#', '/contact', '/about', '/privacy', '/terms', '/search',
    '/cdn-cgi/', 'email-protection', 'video_story_inside',
    '/sports-news/', '/technology-news/', '/entertainment-news/',
    '/hot-news/', '/author-biography/', '/more', 'news_archive',
    '/index.php', '/rss', '/mobi/', 'disqus', 'exchange-rates',
    'indicative-rates', 'news-bulletin', 'story-tab', 'viewed-tab', '?p=',
    '/home', '/latest', '/category/', '/tag/', '/page/',
    '/feed', '/amp/', '/print/', '/gallery/', '/video/',
]


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self._parts.append(cleaned)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def is_article_url(url: str) -> bool:
    url_lower = url.lower()
    return not any(pattern in url_lower for pattern in SKIP_PATTERNS)


def choose_user_agent() -> str:
    return random.choice(USER_AGENTS)


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_same_or_subdomain(site_url: str, candidate_url: str) -> bool:
    site_domain = domain_of(site_url).lstrip("www.")
    candidate_domain = domain_of(candidate_url).lstrip("www.")
    return candidate_domain == site_domain or candidate_domain.endswith(f".{site_domain}")


def tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def strip_html(html_text: str) -> str:
    clean_html = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    stripper = _HTMLStripper()
    stripper.feed(clean_html)
    return html.unescape(stripper.get_text())


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def parse_metadata_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return normalize_datetime(value)
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return normalize_datetime(parsed)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue

    return None
