import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin
import httpx
import trafilatura
from trafilatura.spider import focused_crawler

from src.collection.core.utils import domain_of, is_article_url, parse_metadata_datetime
from src.collection.core.http_client import fetch

logger = logging.getLogger(__name__)

SITE_DISCOVERY_MAX_SEEN_URLS = 75
SITE_DISCOVERY_MAX_KNOWN_URLS = 120
SITE_DISCOVERY_SCAN_LIMIT = 75

_CRAWLER_SKIP_DOMAINS_DEFAULT = {"newsfirst.lk", "english.newsfirst.lk"}
CRAWLER_SKIP_DOMAINS: set[str] = {
    d.strip().lower() for d in os.getenv("CRAWLER_SKIP_DOMAINS", "").split(",") if d.strip()
} or _CRAWLER_SKIP_DOMAINS_DEFAULT


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


async def collect_articles_from_site(outlet_name: str, site_url: str, client: httpx.AsyncClient, days_back: int = 90, max_articles: int = 50):
    articles_data = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    domain = domain_of(site_url).lstrip("www.")
    if domain in CRAWLER_SKIP_DOMAINS or any(domain.endswith(f".{d}") for d in CRAWLER_SKIP_DOMAINS):
        logger.info("[CRAWLER] Skipping focused_crawler for %s (%s)", outlet_name, domain)
        return articles_data

    try:
        logger.info("Starting primary site discovery for %s: %s", outlet_name, site_url)
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
            logger.warning("Crawler timed out for %s", outlet_name)
            return articles_data
        candidate_urls = [u for u in _coerce_known_urls(known_urls, site_url) if is_article_url(u)]

        async def process_url(article_url: str) -> dict[str, str] | None:
            if not is_article_url(article_url):
                return None
            try:
                response = await fetch(client, article_url)
                extracted_json = trafilatura.extract(
                    response.text, output_format='json', with_metadata=True, include_comments=False, include_tables=False
                )
                if not extracted_json:
                    return None

                payload = json.loads(extracted_json)
                pub = parse_metadata_datetime(payload.get("date")) or datetime.now()
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
                logger.debug(f"site crawl fallback failed for {article_url}: {e}")
                return None

        scan_urls = candidate_urls[: min(max_articles * 2, SITE_DISCOVERY_SCAN_LIMIT)]
        if not scan_urls:
            logger.warning(f"No articles found for {outlet_name} from crawl fallback")
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
        logger.warning(f"Site crawl fallback failed for {outlet_name}: {e}")

    return articles_data
