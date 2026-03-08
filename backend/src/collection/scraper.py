import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import atoma
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
MAX_KNOWN_URLS = 1000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
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

_REQUEST_SEMAPHORE: asyncio.Semaphore | None = None


def is_article_url(url: str) -> bool:
    url_lower = url.lower()
    return not any(pattern in url_lower for pattern in SKIP_PATTERNS)

def load_outlets_from_db():
    from prisma import Prisma

    db = Prisma()
    db.connect()
    try:
        outlets = db.outlet.find_many()
        outlet_configs = []

        for outlet in outlets:
            feeds = outlet.rss_feeds
            if isinstance(feeds, str):
                try:
                    feeds = json.loads(feeds)
                except Exception:
                    feeds = []

            if not isinstance(feeds, list):
                feeds = []

            outlet_configs.append(
                {
                    "name": outlet.name,
                    "url": outlet.url,
                    "rss_feeds": [f.strip() for f in feeds if isinstance(f, str) and f.strip()],
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


def _get_entry_title(entry: Any) -> str:
    title = getattr(entry, "title", None)
    if isinstance(title, str) and title.strip():
        return title.strip()

    nested = getattr(title, "value", None)
    if isinstance(nested, str) and nested.strip():
        return nested.strip()

    return "Untitled"


def _get_entry_url(entry: Any) -> str:
    link = getattr(entry, "link", None)
    if isinstance(link, str) and link.strip():
        return link.strip()

    links = getattr(entry, "links", None)
    if isinstance(links, list):
        for item in links:
            href = getattr(item, "href", None)
            if isinstance(href, str) and href.strip():
                return href.strip()

    return ""


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
    if _REQUEST_SEMAPHORE is None:
        response = await client.get(url, follow_redirects=True)
    else:
        async with _REQUEST_SEMAPHORE:
            response = await client.get(url, follow_redirects=True)

    response.raise_for_status()
    return response


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


async def collect_articles_from_rss(outlet_name, feeds, client, days_back=90):
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    for feed_url in feeds:
        logging.info(f"Parsing RSS feed for {outlet_name}: {feed_url}")

        try:
            response = await _get_with_semaphore(client, feed_url)
            feed_bytes = response.content
        except Exception as e:
            logging.error(f"Error fetching feed for {outlet_name}: {e}")
            continue

        try:
            feed = atoma.parse_rss_bytes(feed_bytes)
            entries = getattr(feed, "items", [])
        except Exception:
            try:
                feed = atoma.parse_atom_bytes(feed_bytes)
                entries = getattr(feed, "entries", [])
            except Exception as e:
                logging.error(f"Error parsing feed for {outlet_name}: {e}")
                continue

        for entry in entries:
            try:
                dt = _normalize_datetime(
                    getattr(entry, "pub_date", None)
                    or getattr(entry, "published", None)
                    or getattr(entry, "updated", None)
                )
                if dt is None:
                    # As a last resort include the article but mark with current time
                    logging.warning(f"Missing/unknown date for entry; including anyway: {_get_entry_title(entry)}")
                    dt = datetime.now()

                # check if it's within our time window (e.g., last 3 months)
                # Note: RSS feeds rarely go back 3 months, they usually only have the latest 50-100 items.
                if dt >= cutoff_date:
                    url = _get_entry_url(entry)
                    if not url:
                        logging.debug(f"Skipping feed entry without URL for {outlet_name}")
                        continue

                    articles_data.append({
                        "outlet": outlet_name,
                        "date": dt.strftime('%Y-%m-%d %H:%M:%S'),
                        "title": _get_entry_title(entry),
                        "url": url
                    })
            except Exception as e:
                logging.error(f"Error parsing entry in {outlet_name}: {e}")

    return articles_data


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
    """Primary discovery: crawl site URLs and extract metadata with trafilatura."""
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
                logging.debug(f"site fallback failed for {article_url}: {e}")
                return None

        scan_urls = candidate_urls[: min(max_articles * 2, SITE_DISCOVERY_SCAN_LIMIT)]
        if not scan_urls:
            logging.warning(f"No articles found for {outlet_name} from site fallback")
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
        logging.warning(f"Site scraping fallback failed for {outlet_name}: {e}")

    return articles_data


async def process_outlet(outlet, client, days_back):
    outlet_name = outlet["name"]
    info = {
        "rss_feeds": outlet.get("rss_feeds", []),
        "url": outlet.get("url"),
    }
    logging.info(f"Starting data collection for {outlet_name}")

    outlet_articles = []
    if info.get("url"):
        site_articles = await collect_articles_from_site(
            outlet_name,
            info.get("url"),
            client,
            days_back=days_back,
            max_articles=50,
        )
        outlet_articles.extend(site_articles)
        logging.info(f"Primary site discovery found {len(site_articles)} articles for {outlet_name}")
    else:
        logging.warning(f"Outlet {outlet_name} has no URL configured for site fallback")

    rss_feeds = info.get("rss_feeds") or []
    if rss_feeds:
        rss_articles = await collect_articles_from_rss(outlet_name, rss_feeds, client, days_back)
        outlet_articles.extend(rss_articles)
        logging.info(f"Found {len(rss_articles)} articles in RSS for {outlet_name}")
    else:
        logging.info(f"No RSS feeds configured for {outlet_name}; RSS fallback skipped")

    deduped_for_outlet: dict[str, dict[str, str]] = {}
    for article in outlet_articles:
        url = article.get("url")
        if isinstance(url, str) and url and url not in deduped_for_outlet:
            deduped_for_outlet[url] = article

    deduped_list = list(deduped_for_outlet.values())
    if deduped_list:
        return deduped_list

    logging.warning(f"No articles found for {outlet_name} from RSS or site fallback")
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

                db.article.upsert(
                    where={'url': article['url']},
                    data={
                        'create': {
                            'outlet': article['outlet'],
                            'date': dt,
                            'title': article['title'],
                            'url': article['url'],
                            'text': article['text']
                        },
                        'update': {
                            'text': article['text'],
                            'title': article['title']
                        }
                    }
                )
            logging.info(f"Saved {len(valid_articles)} articles to DB")
        finally:
            db.disconnect()
    except Exception as e:
        logging.error(f"DB Error while saving articles: {e}")


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
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            # 1. Gather URLs and metadata from site first, then RSS fallback
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

                content = await scrape_article_content(article['url'], client)
                processed = dict(article)
                processed['text'] = content

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
        # For MVP, try to collect what's available now
        # Note: RSS only gives recent articles. To get 3 months, we'd need to scrape archives
        # Let's start with site crawling + RSS fallback and keep the pipeline resilient.
        asyncio.run(collect_data(days_back=90))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
