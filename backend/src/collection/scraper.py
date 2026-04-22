import asyncio
import json
import logging
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import sentry_sdk
import trafilatura
from tenacity import RetryCallState, retry, stop_after_attempt, wait_exponential
from trafilatura.spider import focused_crawler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.2)

SCRAPE_MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 12
MAX_CONCURRENT_REQUESTS = 10
MAX_ARTICLES_PER_OUTLET = int(os.getenv("MAX_ARTICLES_PER_OUTLET", "300"))
MAX_SITEMAP_URLS_PER_OUTLET = int(os.getenv("MAX_SITEMAP_URLS_PER_OUTLET", "4000"))
MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", "0.5"))
MAX_DELAY_SECONDS = float(os.getenv("MAX_DELAY_SECONDS", "2.0"))
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
    'indicative-rates', 'news-bulletin', 'story-tab', 'viewed-tab',
]
SITE_DISCOVERY_MAX_SEEN_URLS = 75
SITE_DISCOVERY_MAX_KNOWN_URLS = 120
SITE_DISCOVERY_SCAN_LIMIT = 75
WAYBACK_ENABLED_DOMAINS = {"adaderana.lk", "dailymirror.lk"}

_REQUEST_SEMAPHORE: asyncio.Semaphore | None = None
_DOMAIN_LOCKS: dict[str, asyncio.Lock] = {}
_DOMAIN_LAST_REQUEST_AT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, RobotFileParser] = {}


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

def load_outlets_from_db():
    from prisma import Prisma

    db = Prisma()
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


async def collect_articles_from_sitemaps(
    outlet_name: str,
    site_url: str,
    client: httpx.AsyncClient,
    days_back: int,
    max_articles: int,
) -> list[dict[str, str]]:
    """Discover article URLs from sitemap index/urlset documents first."""
    cutoff_date = datetime.now() - timedelta(days=days_back)
    seeds = await _discover_sitemaps(site_url, client)
    queue = list(seeds)
    visited_sitemaps: set[str] = set()
    discovered_articles: dict[str, dict[str, str]] = {}

    while queue and len(discovered_articles) < max_articles and len(visited_sitemaps) < MAX_SITEMAP_URLS_PER_OUTLET:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sitemap_url)

        try:
            response = await _get_with_semaphore(client, sitemap_url)
        except Exception as e:
            logging.debug(f"Could not fetch sitemap {sitemap_url}: {e}")
            continue

        try:
            root = ET.fromstring(response.text)
        except Exception:
            logging.debug(f"Invalid XML in sitemap: {sitemap_url}")
            continue

        root_tag = _tag_name(root.tag)
        if root_tag == "sitemapindex":
            for child in root:
                if _tag_name(child.tag) != "sitemap":
                    continue
                loc = None
                for node in child:
                    if _tag_name(node.tag) == "loc" and node.text:
                        loc = node.text.strip()
                        break
                if loc and loc not in visited_sitemaps and _is_same_or_subdomain(site_url, loc):
                    queue.append(loc)
            continue

        if root_tag != "urlset":
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
                "date": (pub or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
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

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y%m%d")
    until = datetime.utcnow().strftime("%Y%m%d")
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
        logging.warning(f"Wayback lookup failed for {outlet_name}: {e}")
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
            dt = datetime.utcnow()

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


def _scrape_retry_error_callback(retry_state: RetryCallState) -> str:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    url = retry_state.args[0] if retry_state.args else "unknown"
    logging.error(f"Failed to scrape content from {url} after {SCRAPE_MAX_RETRIES} attempts: {exc}")
    return ""


@retry(
    stop=stop_after_attempt(SCRAPE_MAX_RETRIES),
    wait=wait_exponential(multiplier=1.5, min=1.5, max=6),
    before_sleep=_log_retry_before_sleep,
    retry_error_callback=_scrape_retry_error_callback,
    reraise=False,
)
async def scrape_article_content(url, client):
    response = await _get_with_semaphore(client, url)
    extracted = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=False,
    )

    if not extracted or not extracted.strip():
        raise ValueError("Trafilatura returned empty text")

    return extracted


async def collect_articles_from_site(outlet_name, site_url, client, days_back=90, max_articles=50):
    """Fallback discovery: crawl site URLs and extract metadata with trafilatura."""
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    try:
        logging.info(f"Starting primary site discovery for {outlet_name}: {site_url}")
        _, known_urls = await asyncio.to_thread(
            focused_crawler,
            site_url,
            max_seen_urls=SITE_DISCOVERY_MAX_SEEN_URLS,
            max_known_urls=SITE_DISCOVERY_MAX_KNOWN_URLS,
        )
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


async def process_outlet(outlet, client, days_back):
    outlet_name = outlet["name"]
    info = {"url": outlet.get("url")}
    logging.info(f"Starting data collection for {outlet_name}")

    outlet_articles = []
    site_url = info.get("url")
    if isinstance(site_url, str) and site_url:
        sitemap_articles = await collect_articles_from_sitemaps(
            outlet_name,
            site_url,
            client,
            days_back=days_back,
            max_articles=MAX_ARTICLES_PER_OUTLET,
        )
        outlet_articles.extend(sitemap_articles)
        logging.info(f"Sitemap discovery found {len(sitemap_articles)} article URLs for {outlet_name}")

        wayback_articles = await collect_wayback_urls(
            outlet_name,
            site_url,
            client,
            days_back=days_back,
            max_articles=max(100, MAX_ARTICLES_PER_OUTLET // 2),
        )
        outlet_articles.extend(wayback_articles)
        if wayback_articles:
            logging.info(f"Wayback discovery found {len(wayback_articles)} article URLs for {outlet_name}")

        if len(outlet_articles) < max(30, MAX_ARTICLES_PER_OUTLET // 4):
            site_articles = await collect_articles_from_site(
                outlet_name,
                site_url,
                client,
                days_back=days_back,
                max_articles=max(50, MAX_ARTICLES_PER_OUTLET // 3),
            )
            outlet_articles.extend(site_articles)
            logging.info(f"Crawler fallback found {len(site_articles)} article URLs for {outlet_name}")
    else:
        logging.warning(f"Outlet {outlet_name} has no URL configured for web discovery")

    deduped_for_outlet: dict[str, dict[str, str]] = {}
    for article in outlet_articles:
        url = article.get("url")
        if isinstance(url, str) and url and url not in deduped_for_outlet:
            deduped_for_outlet[url] = article

    deduped_list = list(deduped_for_outlet.values())
    if deduped_list:
        return deduped_list

    logging.warning(f"No articles found for {outlet_name} via web discovery")
    return []

def save_to_db(valid_articles):
    if not valid_articles:
        logging.warning("No valid articles collected.")
        return

    try:
        from prisma import Prisma
        db = Prisma()
        db.connect()
        try:
            for article in valid_articles:
                # We must convert date string to datetime to avoid Prisma validation error
                dt = datetime.strptime(article['date'], '%Y-%m-%d %H:%M:%S')
                base_create = {
                    'outlet': article['outlet'],
                    'date': dt,
                    'title': article['title'],
                    'url': article['url'],
                    'text': article['text'],
                }
                base_update = {
                    'text': article['text'],
                    'title': article['title'],
                }

                # Store raw_html when Prisma schema/client includes it.
                if article.get('raw_html'):
                    base_create['raw_html'] = article['raw_html']
                    base_update['raw_html'] = article['raw_html']

                try:
                    data_payload = cast(Any, {
                        'create': base_create,
                        'update': base_update,
                    })
                    db.article.upsert(
                        where={'url': article['url']},
                        data=data_payload
                    )
                except Exception as e:
                    message = str(e)
                    if 'raw_html' in message:
                        # Backward compatibility until prisma client is regenerated.
                        base_create.pop('raw_html', None)
                        base_update.pop('raw_html', None)
                        fallback_payload = cast(Any, {
                            'create': base_create,
                            'update': base_update,
                        })
                        db.article.upsert(
                            where={'url': article['url']},
                            data=fallback_payload
                        )
                    else:
                        raise
            logging.info(f"Saved {len(valid_articles)} articles to DB")
        finally:
            db.disconnect()
    except Exception as e:
        logging.error(f"DB Error while saving articles: {e}")


@retry(
    stop=stop_after_attempt(SCRAPE_MAX_RETRIES),
    wait=wait_exponential(multiplier=1.5, min=1.5, max=6),
    before_sleep=_log_retry_before_sleep,
    retry_error_callback=_scrape_retry_error_callback,
    reraise=False,
)
async def scrape_article_payload(url: str, client: httpx.AsyncClient) -> dict[str, str]:
    response = await _get_with_semaphore(client, url)
    raw_html = response.text
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
    global _REQUEST_SEMAPHORE

    all_articles = []
    outlets = await asyncio.to_thread(load_outlets_from_db)

    if not outlets:
        logging.warning("No outlets configured in DB. Add outlets before running scraper.")
        return

    _REQUEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    try:
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 1. Gather URLs and metadata from sitemaps first, then fallback discovery.
            outlet_results = await asyncio.gather(*(process_outlet(outlet, client, days_back) for outlet in outlets))
            all_articles = [article for result in outlet_results for article in result]

            # Global URL dedupe across all outlets
            deduped_global: dict[str, dict[str, str]] = {}
            for article in all_articles:
                url = article.get("url")
                if isinstance(url, str) and url and url not in deduped_global:
                    deduped_global[url] = article
            all_articles = list(deduped_global.values())

            # 2. Scrape full content for gathered URLs
            logging.info(f"Scraping full content for {len(all_articles)} articles concurrently...")

            total_articles = len(all_articles)
            progress_count = 0
            progress_lock = asyncio.Lock()

            async def process_article(article: dict[str, str]) -> dict[str, str]:
                nonlocal progress_count

                payload = await scrape_article_payload(article['url'], client)
                processed = dict(article)
                processed['text'] = payload['text']
                processed['raw_html'] = payload['raw_html']
                if payload.get('title'):
                    processed['title'] = payload['title']
                if payload.get('date'):
                    processed['date'] = payload['date']

                async with progress_lock:
                    progress_count += 1
                    if progress_count % 10 == 0 or progress_count == total_articles:
                        logging.info(f"Scraping progress: {progress_count}/{total_articles}")

                return processed

            processed_articles = await asyncio.gather(*(process_article(art) for art in all_articles))
            all_articles = processed_articles

            # Filter out articles where we couldn't get text
            valid_articles = [a for a in all_articles if a.get('text') and len(a['text'].strip()) > 50]

            # 3. Save to DB
            if not valid_articles:
                logging.warning("No valid articles collected.")
                return

            await asyncio.to_thread(save_to_db, valid_articles)
    finally:
        _REQUEST_SEMAPHORE = None

if __name__ == "__main__":
    try:
        # Sitemap-first web backfill for historical outlet profiling.
        asyncio.run(collect_data(days_back=90))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
