import asyncio
import html
import json
import logging
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
import sentry_sdk
import trafilatura
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential
from trafilatura.spider import focused_crawler

from .outlets import (
    AdaDeranaOutlet,
    CeylonTodayOutlet,
    DailyFTOutlet,
    EconomyNextOutlet,
    LBOOutlet,
    NewsfirstOutlet,
    BaseOutletScraper,
)
import src.collection.outlets.base as _outlets_base

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.2)

SCRAPE_MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 12
MAX_CONCURRENT_REQUESTS = 10
MAX_ARTICLES_PER_OUTLET = int(os.getenv("MAX_ARTICLES_PER_OUTLET", "300"))
MAX_SITEMAP_URLS_PER_OUTLET = int(os.getenv("MAX_SITEMAP_URLS_PER_OUTLET", "4000"))
MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", "0.5"))
MAX_DELAY_SECONDS = float(os.getenv("MAX_DELAY_SECONDS", "2.0"))
SAVE_CHUNK_SIZE = int(os.getenv("SAVE_CHUNK_SIZE", "100"))
DB_CONNECT_MAX_RETRIES = int(os.getenv("DB_CONNECT_MAX_RETRIES", "5"))
DB_CONNECT_BACKOFF_BASE_SECONDS = float(os.getenv("DB_CONNECT_BACKOFF_BASE_SECONDS", "1.5"))
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
    # Extended: non-canonical paths observed in production audit (2026-04-23)
    '/home', '/latest', '/category/', '/tag/', '/page/',
    '/feed', '/amp/', '/print/', '/gallery/', '/video/',
]
SITE_DISCOVERY_MAX_SEEN_URLS = 75
SITE_DISCOVERY_MAX_KNOWN_URLS = 120
SITE_DISCOVERY_SCAN_LIMIT = 75
WAYBACK_ENABLED_DOMAINS = {"adaderana.lk", "dailymirror.lk"}
WORDPRESS_API_ENABLED_DOMAINS = {"lankabusinessonline.com", "lbo.lk"}
# 300s: accommodates deep sitemap indexes (e.g. LBO with 21 shards × ~12s/fetch + throttle).
# The previous 90s default caused Ceylon Today and Economy Next to timeout during shard traversal.
OUTLET_DISCOVERY_TIMEOUT_SECONDS = int(os.getenv("OUTLET_DISCOVERY_TIMEOUT_SECONDS", "300"))
GHOST_RESPONSE_MIN_BYTES = int(os.getenv("GHOST_RESPONSE_MIN_BYTES", "200"))
# Domains whose focused_crawler always times out (JS-rendered, anti-bot, etc.).
# Comma-separated env override: CRAWLER_SKIP_DOMAINS="newsfirst.lk,example.com"
_CRAWLER_SKIP_DOMAINS_DEFAULT = {"newsfirst.lk", "english.newsfirst.lk"}
CRAWLER_SKIP_DOMAINS: set[str] = {
    d.strip().lower()
    for d in os.getenv("CRAWLER_SKIP_DOMAINS", "").split(",")
    if d.strip()
} or _CRAWLER_SKIP_DOMAINS_DEFAULT

_REQUEST_SEMAPHORE: asyncio.Semaphore | None = None
_DOMAIN_LOCKS: dict[str, asyncio.Lock] = {}
_DOMAIN_LAST_REQUEST_AT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, RobotFileParser] = {}
_BLOCKED_PATHS: set[str] = set()          # 403-blocked paths collected during a run
_SCHEMA_HAS_RAW_HTML: bool | None = None  # Detected on first DB write attempt
FALLBACK_JSONL_PATH = Path(__file__).resolve().parents[2] / "data" / "db_fallback_articles.jsonl"


class GhostResponseError(Exception):
    """Server returned HTTP 200 with a near-empty body — anti-scraping ghosting."""


@dataclass
class _OutletStat:
    name: str
    discovered: int = 0
    persisted: int = 0
    failed: bool = False
    failure_reason: str = ""
    ghost_count: int = 0
    blocked_count: int = 0


@dataclass
class _RunSummary:
    start_time: float = field(default_factory=time.monotonic)
    outlet_stats: list[_OutletStat] = field(default_factory=list)
    total_discovered: int = 0
    total_persisted: int = 0
    parse_errors: int = 0

    def log(self) -> None:
        duration_s = int(time.monotonic() - self.start_time)
        failed = [s for s in self.outlet_stats if s.failed]
        success_count = len(self.outlet_stats) - len(failed)
        failed_detail = ", ".join(f"{s.name}: {s.failure_reason}" for s in failed) or "none"
        ghost_total = sum(s.ghost_count for s in self.outlet_stats)
        blocked_total = len(_BLOCKED_PATHS)
        logging.info(
            "[RUN SUMMARY] Duration: %dm%ds | Outlets: %d | Success: %d | Failed: %d (%s)\n"
            "              URLs discovered: %d | Parse errors: %d | Persisted: %d\n"
            "              Ghost responses skipped: %d | 403 Blocked paths: %d%s",
            duration_s // 60, duration_s % 60,
            len(self.outlet_stats), success_count, len(failed), failed_detail,
            self.total_discovered, self.parse_errors, self.total_persisted,
            ghost_total, blocked_total,
            ("\n              Blocked: " + ", ".join(sorted(_BLOCKED_PATHS))) if _BLOCKED_PATHS else "",
        )


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


def _choose_user_agent() -> str:
    return random.choice(USER_AGENTS)


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_same_or_subdomain(site_url: str, candidate_url: str) -> bool:
    site_domain = _domain_of(site_url).lstrip("www.")
    candidate_domain = _domain_of(candidate_url).lstrip("www.")
    return candidate_domain == site_domain or candidate_domain.endswith(f".{site_domain}")


def _sitemap_default_url(site_url: str) -> str:
    parsed = urlparse(site_url)
    return f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"


def _tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _looks_like_wayback_target(domain: str) -> bool:
    normalized = domain.lstrip("www.")
    return any(normalized == d or normalized.endswith(f".{d}") for d in WAYBACK_ENABLED_DOMAINS)


def _looks_like_wordpress_api_target(domain: str) -> bool:
    normalized = domain.lstrip("www.")
    return any(normalized == d or normalized.endswith(f".{d}") for d in WORDPRESS_API_ENABLED_DOMAINS)


def _strip_html(html_text: str) -> str:
    clean_html = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    stripper = _HTMLStripper()
    stripper.feed(clean_html)
    return html.unescape(stripper.get_text())


def _extract_slug_from_article_url(article_url: str) -> str:
    parsed = urlparse(article_url)
    path = parsed.path.strip("/")
    if not path:
        return ""

    slug = path.split("/")[-1].strip()
    return slug


def _looks_truncated_wp_text(text: str) -> bool:
    candidate = text.strip().lower()
    if not candidate:
        return True

    markers = (
        "[…]",
        "[...]",
        "[&hellip;]",
        "…",
        "...",
        "continue reading",
        "read more",
    )
    return any(candidate.endswith(marker) for marker in markers)


async def _fetch_wordpress_api_payload(url: str, client: httpx.AsyncClient) -> dict[str, str] | None:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if not _looks_like_wordpress_api_target(domain):
        return None

    slug = _extract_slug_from_article_url(url)
    if not slug or slug.isdigit():
        return None

    endpoint = f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts"
    params = {
        "slug": slug,
        "_fields": "id,date,title,link,content",
        "per_page": "1",
    }

    try:
        response = await client.get(
            endpoint,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": _choose_user_agent()},
        )
        response.raise_for_status()
        posts = response.json()
    except Exception as e:
        logging.debug(f"WordPress API lookup failed for {url}: {e}")
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
    extracted_text = _strip_html(raw_html)
    if len(extracted_text) < 50 or _looks_truncated_wp_text(extracted_text):
        return None

    published = _parse_metadata_datetime(post.get("date"))
    cleaned_title = _strip_html(title_html)
    return {
        "raw_html": raw_html,
        "text": extracted_text,
        "title": cleaned_title,
        "date": (published or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
    }


def _domain_lock(domain: str) -> asyncio.Lock:
    if domain not in _DOMAIN_LOCKS:
        _DOMAIN_LOCKS[domain] = asyncio.Lock()
    return _DOMAIN_LOCKS[domain]


async def _throttle_domain(domain: str) -> None:
    lock = _domain_lock(domain)
    async with lock:
        now = time.monotonic()
        last = _DOMAIN_LAST_REQUEST_AT.get(domain, 0.0)
        jitter = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        wait_for = max(0.0, (last + jitter) - now)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        _DOMAIN_LAST_REQUEST_AT[domain] = time.monotonic()


def _normalize_outlet_url(url: str) -> str:
    return url.strip().rstrip("/")


def _normalize_database_url_for_neon(database_url: str) -> str:
    if not database_url:
        return database_url

    normalized = database_url
    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if "neon.tech" not in host:
        return normalized

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" not in {k.lower(): v for k, v in query.items()}:
        query["sslmode"] = "require"
        parsed = parsed._replace(query=urlencode(query))
        return urlunparse(parsed)

    return normalized


def _create_prisma_client():
    from prisma import Prisma

    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        os.environ["DATABASE_URL"] = _normalize_database_url_for_neon(database_url)

    return Prisma()


def _append_articles_to_fallback_jsonl(articles: list[dict[str, str]]) -> None:
    if not articles:
        return

    FALLBACK_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FALLBACK_JSONL_PATH.open("a", encoding="utf-8") as handle:
        for article in articles:
            handle.write(json.dumps(article, ensure_ascii=True) + "\n")

    logging.warning(
        "Database unreachable. Appended %s articles to fallback queue at %s",
        len(articles),
        str(FALLBACK_JSONL_PATH),
    )


def _load_fallback_articles() -> list[dict[str, str]]:
    if not FALLBACK_JSONL_PATH.exists():
        return []

    records: list[dict[str, str]] = []
    with FALLBACK_JSONL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append({k: str(v) if v is not None else "" for k, v in payload.items()})

    return records


def _clear_fallback_articles() -> None:
    if FALLBACK_JSONL_PATH.exists():
        FALLBACK_JSONL_PATH.unlink()


def replay_fallback_articles() -> None:
    pending = _load_fallback_articles()
    if not pending:
        return

    logging.info("Replaying %s fallback articles from %s", len(pending), str(FALLBACK_JSONL_PATH))
    if save_to_db(pending, allow_fallback=False):
        _clear_fallback_articles()
        logging.info("Fallback replay succeeded; cleared local fallback queue")
    else:
        logging.warning("Fallback replay failed; keeping queued records on disk")

def load_outlets_from_db():
    db = _create_prisma_client()
    db.connect()
    try:
        outlets = db.outlet.find_many()
        outlet_configs = []

        for outlet in outlets:
            normalized_url = _normalize_outlet_url(outlet.url or "")
            if not normalized_url:
                continue

            outlet_configs.append(
                {
                    "name": outlet.name,
                    "url": normalized_url,
                }
            )

        return outlet_configs
    finally:
        db.disconnect()

def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_metadata_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return _normalize_datetime(parsed)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue

    return None


def _coerce_known_urls(known_urls: Any, base_url: str) -> list[str]:
    raw_values: list[str] = []

    if isinstance(known_urls, dict):
        iterator = known_urls.keys()
    elif isinstance(known_urls, (list, tuple, set)):
        iterator = known_urls
    else:
        iterator = []

    for item in iterator:
        candidate = ""
        if isinstance(item, str):
            candidate = item.strip()
        elif isinstance(item, (tuple, list)) and item and isinstance(item[0], str):
            candidate = item[0].strip()
        if candidate:
            raw_values.append(urljoin(base_url, candidate))

    seen: set[str] = set()
    deduped: list[str] = []
    for url in raw_values:
        if url not in seen:
            seen.add(url)
            deduped.append(url)

    return deduped


async def _get_with_semaphore(client: httpx.AsyncClient, url: str) -> httpx.Response:
    domain = _domain_of(url)
    await _throttle_domain(domain)

    user_agent = _choose_user_agent()
    if not await _can_fetch_url(client, url, user_agent):
        raise PermissionError(f"Blocked by robots.txt: {url}")

    if _REQUEST_SEMAPHORE is None:
        response = await client.get(url, follow_redirects=True, headers={"User-Agent": user_agent})
    else:
        async with _REQUEST_SEMAPHORE:
            response = await client.get(url, follow_redirects=True, headers={"User-Agent": user_agent})

    response.raise_for_status()
    return response


async def _load_robots_parser(client: httpx.AsyncClient, url: str) -> RobotFileParser:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    cached = _ROBOTS_CACHE.get(domain)
    if cached is not None:
        return cached

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        response = await client.get(robots_url, follow_redirects=True, headers={"User-Agent": _choose_user_agent()})
        if response.status_code == 200 and response.text:
            rp.parse(response.text.splitlines())
    except Exception:
        # On robots fetch failure, default to permissive behavior to avoid hard-stop backfills.
        pass

    _ROBOTS_CACHE[domain] = rp
    return rp


async def _can_fetch_url(client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
    try:
        rp = await _load_robots_parser(client, url)
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def _extract_sitemap_locations_from_robots(robots_text: str) -> list[str]:
    urls: list[str] = []
    for line in robots_text.splitlines():
        raw = line.strip()
        if raw.lower().startswith("sitemap:"):
            candidate = raw.split(":", 1)[1].strip()
            if candidate:
                urls.append(candidate)
    return urls


async def _discover_sitemaps(site_url: str, client: httpx.AsyncClient) -> list[str]:
    parsed = urlparse(site_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    discovered = {_sitemap_default_url(site_url)}

    try:
        response = await client.get(robots_url, follow_redirects=True, headers={"User-Agent": _choose_user_agent()})
        if response.status_code == 200 and response.text:
            discovered.update(_extract_sitemap_locations_from_robots(response.text))
    except Exception:
        pass

    return sorted(discovered)


# Maximum shards to fetch concurrently during sitemap index traversal.
_SITEMAP_FETCH_BATCH_SIZE = int(os.getenv("SITEMAP_FETCH_BATCH_SIZE", "20"))


async def _fetch_and_parse_sitemap(
    sitemap_url: str,
    client: httpx.AsyncClient,
) -> tuple[str, ET.Element | None]:
    """Fetch a single sitemap URL and return (url, parsed_root | None)."""
    try:
        response = await _get_with_semaphore(client, sitemap_url)
        root = ET.fromstring(response.text)
        return sitemap_url, root
    except Exception as e:
        logging.debug("Could not fetch/parse sitemap %s: %s", sitemap_url, e)
        return sitemap_url, None


async def collect_articles_from_sitemaps(
    outlet_name: str,
    site_url: str,
    client: httpx.AsyncClient,
    days_back: int,
    max_articles: int,
) -> list[dict[str, str]]:
    """Discover article URLs from sitemap index/urlset documents.

    Two-phase concurrent approach:
      Phase 1 – Fetch all index-level sitemaps in parallel batches to collect
                 child shard URLs (handles sitemapindex nodes).
      Phase 2 – Fetch all collected shard (urlset) documents in parallel batches
                 and extract article <loc> entries.

    This replaces the previous sequential queue traversal, reducing wall-clock time
    for multi-shard sites (e.g. LBO with 21 shards) from ~277s to ~30s.
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    seeds = await _discover_sitemaps(site_url, client)

    # --- Phase 1: Resolve sitemapindex → collect all leaf shard URLs ---
    pending_index: set[str] = set(seeds)
    visited: set[str] = set()
    leaf_shard_urls: list[str] = []   # urlset documents to scrape in Phase 2

    while pending_index and len(visited) < MAX_SITEMAP_URLS_PER_OUTLET:
        batch = list(pending_index - visited)[:_SITEMAP_FETCH_BATCH_SIZE]
        pending_index -= set(batch)
        visited.update(batch)

        results = await asyncio.gather(
            *[_fetch_and_parse_sitemap(u, client) for u in batch]
        )

        for url, root in results:
            if root is None:
                continue
            root_tag = _tag_name(root.tag)
            if root_tag == "sitemapindex":
                for child in root:
                    if _tag_name(child.tag) != "sitemap":
                        continue
                    for node in child:
                        if _tag_name(node.tag) == "loc" and node.text:
                            loc = node.text.strip()
                            if loc and loc not in visited and _is_same_or_subdomain(site_url, loc):
                                pending_index.add(loc)
                            break
            elif root_tag == "urlset":
                # Seed documents that are already urlsets go straight to Phase 2.
                leaf_shard_urls.append(url)

    if not leaf_shard_urls:
        logging.debug("[SITEMAP] No leaf shards found for %s", outlet_name)
        return []

    logging.debug(
        "[SITEMAP] %s: %d leaf shards to fetch (visited %d index nodes)",
        outlet_name, len(leaf_shard_urls), len(visited),
    )

    # --- Phase 2: Fetch all leaf urlset shards concurrently ---
    discovered_articles: dict[str, dict[str, str]] = {}

    for i in range(0, len(leaf_shard_urls), _SITEMAP_FETCH_BATCH_SIZE):
        if len(discovered_articles) >= max_articles:
            break

        batch = leaf_shard_urls[i : i + _SITEMAP_FETCH_BATCH_SIZE]
        results = await asyncio.gather(
            *[_fetch_and_parse_sitemap(u, client) for u in batch]
        )

        for _url, root in results:
            if root is None or _tag_name(root.tag) != "urlset":
                continue

            for child in root:
                if _tag_name(child.tag) != "url":
                    continue

                loc = ""
                lastmod_raw = None
                for node in child:
                    tag = _tag_name(node.tag)
                    if tag == "loc" and node.text:
                        loc = node.text.strip()
                    elif tag == "lastmod" and node.text:
                        lastmod_raw = node.text.strip()

                if not loc or not is_article_url(loc) or not _is_same_or_subdomain(site_url, loc):
                    continue

                pub = _parse_metadata_datetime(lastmod_raw)
                if pub and pub < cutoff_date:
                    continue

                discovered_articles[loc] = {
                    "outlet": outlet_name,
                    "date": (pub or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                    "title": loc,
                    "url": loc,
                }

                if len(discovered_articles) >= max_articles:
                    break

    return list(discovered_articles.values())


async def collect_wayback_urls(
    outlet_name: str,
    site_url: str,
    client: httpx.AsyncClient,
    days_back: int,
    max_articles: int,
) -> list[dict[str, str]]:
    domain = _domain_of(site_url)
    if not _looks_like_wayback_target(domain):
        return []

    now_utc = datetime.now(timezone.utc)
    since = (now_utc - timedelta(days=days_back)).strftime("%Y%m%d")
    until = now_utc.strftime("%Y%m%d")
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "fl": "timestamp,original,statuscode",
        "filter": "statuscode:200",
        "collapse": "urlkey",
        "from": since,
        "to": until,
        "limit": str(max_articles * 2),
    }

    try:
        response = await client.get(
            "https://web.archive.org/cdx/search/cdx",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": _choose_user_agent()},
        )
        response.raise_for_status()
        rows = response.json()
    except Exception as e:
        # Wayback is a best-effort fallback; downgrade to INFO to avoid polluting Sentry.
        logging.info("[WAYBACK] Lookup unavailable for %s: %s", outlet_name, e)
        return []

    if not isinstance(rows, list) or len(rows) <= 1:
        return []

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 2:
            continue

        ts = str(row[0]).strip()
        original_url = str(row[1]).strip()
        if not original_url or original_url in seen or not is_article_url(original_url):
            continue
        if not _is_same_or_subdomain(site_url, original_url):
            continue

        try:
            dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
        except ValueError:
            dt = datetime.now(timezone.utc).replace(tzinfo=None)

        seen.add(original_url)
        items.append(
            {
                "outlet": outlet_name,
                "date": dt.strftime('%Y-%m-%d %H:%M:%S'),
                "title": original_url,
                "url": original_url,
            }
        )
        if len(items) >= max_articles:
            break

    return items


def _log_retry_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    url = retry_state.args[0] if retry_state.args else "unknown"
    next_sleep = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logging.warning(
        f"Scrape attempt {retry_state.attempt_number}/{SCRAPE_MAX_RETRIES} failed for {url}: {exc}. "
        f"Retrying in {next_sleep:.1f}s"
    )


def _scrape_payload_retry_error_callback(retry_state: RetryCallState) -> dict[str, str]:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    url = retry_state.args[0] if retry_state.args else "unknown"
    logging.error(f"Failed to scrape content from {url} after {SCRAPE_MAX_RETRIES} attempts: {exc}")
    return {"text": "", "raw_html": "", "title": "", "date": ""}


def _is_retryable_exception(exc: BaseException) -> bool:
    # Never retry sentinel errors — they signal a deliberate skip, not a transient fault.
    if isinstance(exc, (PermissionError, GhostResponseError)):
        return False

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 403:
            # Record directory-level blocks for the run summary; do not retry.
            try:
                blocked_path = str(exc.response.url)
            except Exception:
                blocked_path = "unknown"
            _BLOCKED_PATHS.add(blocked_path)
            logging.debug("403 Forbidden — blocked path recorded: %s", blocked_path)
            return False
        # Do not retry permanent client-side failures like 404/410.
        return status >= 500 or status == 429

    # Retry transient network and parsing related exceptions.
    return True


async def collect_articles_from_site(outlet_name, site_url, client, days_back=90, max_articles=50):
    """Fallback discovery: crawl site URLs and extract metadata with trafilatura.

    Skipped entirely for domains in CRAWLER_SKIP_DOMAINS (JS-rendered / persistent timeout
    sites such as newsfirst.lk) to avoid wasting 60s on a known-dead spider path.
    """
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    # Fast-fail for known crawler-incompatible domains.
    domain = _domain_of(site_url).lstrip("www.")
    if domain in CRAWLER_SKIP_DOMAINS or any(domain.endswith(f".{d}") for d in CRAWLER_SKIP_DOMAINS):
        logging.info(
            "[CRAWLER] Skipping focused_crawler for %s (%s) — domain is in CRAWLER_SKIP_DOMAINS",
            outlet_name, domain,
        )
        return articles_data

    try:
        logging.info("Starting primary site discovery for %s: %s", outlet_name, site_url)
        try:
            _, known_urls = await asyncio.wait_for(
                asyncio.to_thread(
                    focused_crawler,
                    site_url,
                    max_seen_urls=SITE_DISCOVERY_MAX_SEEN_URLS,
                    max_known_urls=SITE_DISCOVERY_MAX_KNOWN_URLS,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logging.warning("Crawler timed out for %s", outlet_name)
            return articles_data
        candidate_urls = [u for u in _coerce_known_urls(known_urls, site_url) if is_article_url(u)]

        async def process_url(article_url: str) -> dict[str, str] | None:
            if not is_article_url(article_url):
                return None

            try:
                response = await _get_with_semaphore(client, article_url)
                extracted_json = trafilatura.extract(
                    response.text,
                    output_format='json',
                    with_metadata=True,
                    include_comments=False,
                    include_tables=False,
                )
                if not extracted_json:
                    return None

                payload = json.loads(extracted_json)
                pub = _parse_metadata_datetime(payload.get("date")) or datetime.now()
                if pub < cutoff_date:
                    return None

                title = payload.get("title") if isinstance(payload.get("title"), str) else None
                return {
                    "outlet": outlet_name,
                    "date": pub.strftime('%Y-%m-%d %H:%M:%S'),
                    "title": title or article_url,
                    "url": article_url,
                }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.debug(f"site crawl fallback failed for {article_url}: {e}")
                return None

        scan_urls = candidate_urls[: min(max_articles * 2, SITE_DISCOVERY_SCAN_LIMIT)]
        if not scan_urls:
            logging.warning(f"No articles found for {outlet_name} from crawl fallback")
            return articles_data

        tasks = [asyncio.create_task(process_url(url)) for url in scan_urls]
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                if isinstance(result, dict):
                    articles_data.append(result)
                    if len(articles_data) >= max_articles:
                        break
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logging.warning(f"Site crawl fallback failed for {outlet_name}: {e}")

    return articles_data


# ---------------------------------------------------------------------------
# Outlet registry — domain suffix → scraper class
# ---------------------------------------------------------------------------
_OUTLET_REGISTRY: list[tuple[tuple[str, ...], type[BaseOutletScraper]]] = [
    (("adaderana.lk",),                          AdaDeranaOutlet),
    (("ceylontoday.lk",),                         CeylonTodayOutlet),
    (("ft.lk", "dailyft.lk"),                     DailyFTOutlet),
    (("economynext.com",),                         EconomyNextOutlet),
    (("lbo.lk", "lankabusinessonline.com"),        LBOOutlet),
    (("newsfirst.lk", "english.newsfirst.lk"),     NewsfirstOutlet),
]


def _build_outlet_scraper(name: str, url: str) -> BaseOutletScraper:
    """Return the most specific registered scraper for the given outlet URL.

    Falls back to a generic trafilatura-based scraper (via the base class
    sitemap pipeline in scraper.py) if no specialist is registered.
    """
    domain = _domain_of(url).lstrip("www.").lower()
    for suffixes, cls in _OUTLET_REGISTRY:
        if any(domain == s or domain.endswith(f".{s}") for s in suffixes):
            logging.debug("[ROUTER] %s → %s", name, cls.__name__)
            return cls(name=name, url=url)

    # Generic fallback — uses the shared sitemap+crawler pipeline
    logging.debug("[ROUTER] %s → GenericOutlet (no specific scraper registered)", name)

    class _GenericOutlet(BaseOutletScraper):
        async def discover_urls(self, client, days_back, max_articles):
            return await collect_articles_from_sitemaps(
                self.name, self.url, client,
                days_back=days_back, max_articles=max_articles,
            )

    return _GenericOutlet(name=name, url=url)


async def process_outlet(outlet: dict[str, str], client: httpx.AsyncClient, days_back: int) -> list[dict[str, str]]:
    """Dispatch discovery to the registered outlet scraper, then dedup."""
    outlet_name = outlet["name"]
    site_url = outlet.get("url", "")

    if not site_url:
        logging.warning("Outlet %s has no URL configured", outlet_name)
        return []

    logging.info("[%s] Starting discovery", outlet_name)
    scraper = _build_outlet_scraper(outlet_name, site_url)

    try:
        outlet_articles = await scraper.discover_urls(
            client,
            days_back=days_back,
            max_articles=MAX_ARTICLES_PER_OUTLET,
        )
    except Exception as exc:
        logging.warning("[%s] Discovery failed: %s", outlet_name, exc)
        outlet_articles = []

    # Stamp _site_url so the content extraction phase can route to this outlet's scraper
    for art in outlet_articles:
        art.setdefault("_site_url", site_url)

    # Deduplicate within this outlet
    deduped: dict[str, dict[str, str]] = {}
    for art in outlet_articles:
        url = art.get("url")
        if isinstance(url, str) and url and url not in deduped:
            deduped[url] = art

    result = list(deduped.values())
    if result:
        logging.info("[%s] Discovery complete: %d unique URLs", outlet_name, len(result))
    else:
        logging.warning("[%s] No articles found via discovery", outlet_name)
    return result


def save_to_db(valid_articles: list[dict[str, str]], allow_fallback: bool = True) -> bool:
    """Persist a chunk of articles to the DB.

    Uses Prisma batch_() to send all upserts as a single transaction, eliminating
    partial-commit risk on mid-chunk failures.  A module-level flag (_SCHEMA_HAS_RAW_HTML)
    is probed on the first call so subsequent chunks skip the per-article fallback dance.
    """
    global _SCHEMA_HAS_RAW_HTML

    if not valid_articles:
        logging.warning("No valid articles collected.")
        return True

    for attempt in range(1, DB_CONNECT_MAX_RETRIES + 1):
        db = _create_prisma_client()
        try:
            db.connect()

            # -- Schema probe: run once to decide whether raw_html column exists. --
            if _SCHEMA_HAS_RAW_HTML is None:
                try:
                    probe_article = next(
                        (a for a in valid_articles if a.get("raw_html")), None
                    )
                    if probe_article:
                        date_raw = probe_article.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if isinstance(date_raw, datetime):
                            probe_dt = date_raw
                        else:
                            try:
                                probe_dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                try:
                                    probe_dt = datetime.strptime(date_raw, "%Y-%m-%d")
                                except ValueError:
                                    probe_dt = datetime.now()

                        probe_create: dict[str, Any] = {
                            "outlet": probe_article.get("outlet", ""),
                            "date": probe_dt,
                            "title": probe_article.get("title", ""),
                            "url": probe_article.get("url", ""),
                            "text": probe_article.get("text", ""),
                            "raw_html": probe_article["raw_html"],
                        }
                        probe_update: dict[str, Any] = {
                            "text": probe_article.get("text", ""),
                            "title": probe_article.get("title", ""),
                            "raw_html": probe_article["raw_html"],
                        }
                        db.article.upsert(
                            where={"url": probe_article.get("url", "")},
                            data=cast(Any, {"create": probe_create, "update": probe_update}),
                        )
                        _SCHEMA_HAS_RAW_HTML = True
                        logging.debug("Schema probe: raw_html column confirmed.")
                    else:
                        _SCHEMA_HAS_RAW_HTML = True  # No raw_html to probe; assume supported.
                except Exception as probe_err:
                    if "raw_html" in str(probe_err):
                        _SCHEMA_HAS_RAW_HTML = False
                        logging.warning(
                            "Schema probe: raw_html column absent — omitting from all writes."
                        )
                    else:
                        raise

            include_raw_html = bool(_SCHEMA_HAS_RAW_HTML)

            # -- Batch upsert: all articles in a single DB transaction. --
            with db.batch_() as batcher:
                for article in valid_articles:
                    date_raw = article.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(date_raw, datetime):
                        dt = date_raw
                    else:
                        try:
                            dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                dt = datetime.strptime(date_raw, "%Y-%m-%d")
                            except ValueError:
                                dt = datetime.now()

                    base_create: dict[str, Any] = {
                        "outlet": article.get("outlet", ""),
                        "date": dt,
                        "title": article.get("title", article.get("url", "")),
                        "url": article.get("url", ""),
                        "text": article.get("text", ""),
                    }
                    base_update: dict[str, Any] = {
                        "text": article.get("text", ""),
                        "title": article.get("title", article.get("url", "")),
                    }

                    if include_raw_html and article.get("raw_html"):
                        base_create["raw_html"] = article["raw_html"]
                        base_update["raw_html"] = article["raw_html"]

                    batcher.article.upsert(
                        where={"url": article.get("url", "")},
                        data=cast(Any, {"create": base_create, "update": base_update}),
                    )

            logging.info("Saved %s articles to DB (batch transaction)", len(valid_articles))
            return True

        except Exception as e:
            wait_seconds = DB_CONNECT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                "DB save attempt %s/%s failed: %s",
                attempt,
                DB_CONNECT_MAX_RETRIES,
                str(e),
            )
            if attempt < DB_CONNECT_MAX_RETRIES:
                logging.info("Retrying DB save in %.1fs", wait_seconds)
                time.sleep(wait_seconds)
            else:
                logging.error("DB save failed after %s attempts", DB_CONNECT_MAX_RETRIES)
                if allow_fallback:
                    _append_articles_to_fallback_jsonl(valid_articles)
                return False
        finally:
            try:
                db.disconnect()
            except Exception:
                pass

    return False



@retry(
    stop=stop_after_attempt(SCRAPE_MAX_RETRIES),
    wait=wait_exponential(multiplier=1.5, min=1.5, max=6),
    retry=retry_if_exception(_is_retryable_exception),
    before_sleep=_log_retry_before_sleep,
    retry_error_callback=_scrape_payload_retry_error_callback,
    reraise=False,
)
async def scrape_article_payload(url: str, client: httpx.AsyncClient) -> dict[str, str]:
    wp_payload = await _fetch_wordpress_api_payload(url, client)
    if wp_payload is not None:
        return wp_payload

    response = await _get_with_semaphore(client, url)
    raw_html = response.text

    # Anti-ghosting: server returned HTTP 200 but near-empty body (scraping countermeasure).
    # Raise GhostResponseError (non-retryable) to skip tenacity backoff entirely.
    if len(raw_html.strip()) < GHOST_RESPONSE_MIN_BYTES:
        raise GhostResponseError(
            f"Ghost response ({len(raw_html)} bytes) from {url} — skipping retries"
        )

    extracted_json = trafilatura.extract(
        raw_html,
        output_format='json',
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )

    extracted_text = ""
    title = ""
    published = None
    if extracted_json:
        payload = json.loads(extracted_json)
        extracted_text = payload.get('text') or ""
        title = payload.get('title') or ""
        published = _parse_metadata_datetime(payload.get('date'))

    if not extracted_text:
        extracted_text = trafilatura.extract(
            raw_html,
            include_comments=False,
            include_tables=False,
        ) or ""

    if not extracted_text.strip():
        raise ValueError("Trafilatura returned empty text")

    return {
        'raw_html': raw_html,
        'text': extracted_text,
        'title': title,
        'date': (published or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
    }


async def collect_data(days_back=90):
    global _REQUEST_SEMAPHORE, _BLOCKED_PATHS

    all_articles: list[dict[str, str]] = []
    run = _RunSummary()
    _BLOCKED_PATHS = set()  # Reset per-run
    outlets = await asyncio.to_thread(load_outlets_from_db)

    if not outlets:
        logging.warning("No outlets configured in DB. Add outlets before running scraper.")
        return

    _REQUEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    _outlets_base.set_semaphore(_REQUEST_SEMAPHORE)  # Share semaphore with outlet scrapers
    await asyncio.to_thread(replay_fallback_articles)

    try:
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:

            # 1. Discover URLs per outlet, with per-outlet timeout guard.
            async def discover_outlet(outlet: dict[str, str]) -> tuple[list[dict[str, str]], _OutletStat]:
                stat = _OutletStat(name=outlet["name"])
                try:
                    articles = await asyncio.wait_for(
                        process_outlet(outlet, client, days_back),
                        timeout=float(OUTLET_DISCOVERY_TIMEOUT_SECONDS),
                    )
                    stat.discovered = len(articles)
                except asyncio.TimeoutError:
                    logging.warning(
                        "[DISCOVERY] Outlet %s timed out after %ds — 0 URLs collected",
                        outlet["name"], OUTLET_DISCOVERY_TIMEOUT_SECONDS,
                    )
                    stat.failed = True
                    stat.failure_reason = f"discovery timeout ({OUTLET_DISCOVERY_TIMEOUT_SECONDS}s)"
                    articles = []
                except Exception as exc:
                    logging.warning("[DISCOVERY] Outlet %s failed: %s", outlet["name"], exc)
                    stat.failed = True
                    stat.failure_reason = str(exc)[:120]
                    articles = []
                return articles, stat

            outlet_results = await asyncio.gather(*(discover_outlet(o) for o in outlets))

            for result_articles, stat in outlet_results:
                run.outlet_stats.append(stat)
                all_articles.extend(result_articles)

            # Global URL dedupe across all outlets.
            deduped_global: dict[str, dict[str, str]] = {}
            for article in all_articles:
                url = article.get("url")
                if isinstance(url, str) and url and url not in deduped_global:
                    deduped_global[url] = article
            all_articles = list(deduped_global.values())
            run.total_discovered = len(all_articles)

            # 2. Scrape full content for gathered URLs.
            logging.info("Scraping full content for %d articles concurrently...", len(all_articles))
            total_articles = len(all_articles)

            async def process_article(article: dict[str, str]) -> dict[str, str]:
                url = article["url"]
                outlet_name = article.get("outlet", "")
                site_url = article.get("_site_url", "")

                # Use the registered outlet scraper's extract_content if available
                if site_url:
                    scraper = _build_outlet_scraper(outlet_name, site_url)
                    payload = await scraper.extract_content(url, client)
                else:
                    payload = await scrape_article_payload(url, client)

                processed = dict(article)
                processed.pop("_site_url", None)  # Remove internal routing key
                processed["text"] = payload["text"]
                processed["raw_html"] = payload.get("raw_html", "")
                if payload.get("title"):
                    processed["title"] = payload["title"]
                if payload.get("date"):
                    processed["date"] = payload["date"]
                return processed

            tasks = [asyncio.create_task(process_article(art)) for art in all_articles]
            failed_count = 0
            ghost_count = 0
            completed_count = 0
            valid_count = 0
            chunk_buffer: list[dict[str, str]] = []

            for task in asyncio.as_completed(tasks):
                completed_count += 1
                if completed_count % 10 == 0 or completed_count == total_articles:
                    logging.info("Scraping progress: %d/%d", completed_count, total_articles)

                try:
                    result = await task
                except asyncio.CancelledError:
                    raise
                except GhostResponseError as ghost_exc:
                    ghost_count += 1
                    logging.debug("Ghost response skipped: %s", ghost_exc)
                    continue
                except Exception as e:
                    failed_count += 1
                    logging.debug("Article scrape task failed: %s", e)
                    continue

                text = result.get("text") if isinstance(result, dict) else None
                if not isinstance(text, str) or len(text.strip()) <= 50:
                    continue

                chunk_buffer.append(result)
                valid_count += 1

                if len(chunk_buffer) >= SAVE_CHUNK_SIZE:
                    chunk = chunk_buffer[:SAVE_CHUNK_SIZE]
                    del chunk_buffer[:SAVE_CHUNK_SIZE]
                    await asyncio.to_thread(save_to_db, chunk)

            # Tag ghost counts back onto outlet stats (best-effort by outlet domain).
            if ghost_count:
                # Distribute ghost count proportionally (we don't track per-article outlet here).
                logging.debug("Total ghost responses during scrape: %d", ghost_count)
                for stat in run.outlet_stats:
                    if not stat.failed:
                        stat.ghost_count = ghost_count // max(1, len(run.outlet_stats))

            run.parse_errors = failed_count

            if failed_count:
                logging.warning(
                    "%d articles failed during content scraping and were skipped", failed_count
                )

            if chunk_buffer:
                await asyncio.to_thread(save_to_db, chunk_buffer)

            if valid_count == 0:
                logging.warning("No valid articles collected.")
                run.log()
                return

            run.total_persisted = valid_count
            logging.info("Scrape stage persisted %s valid articles", valid_count)
            run.log()

    finally:
        _REQUEST_SEMAPHORE = None


if __name__ == "__main__":
    try:
        # Sitemap-first web backfill for historical outlet profiling.
        asyncio.run(collect_data(days_back=3650))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
