import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urlparse
import httpx

from src.collection.core.utils import is_same_or_subdomain, is_article_url, parse_metadata_datetime, choose_user_agent, tag_name
from src.collection.core.http_client import fetch

logger = logging.getLogger(__name__)

MAX_SITEMAP_URLS_PER_OUTLET = int(os.getenv("MAX_SITEMAP_URLS_PER_OUTLET", "4000"))
_SITEMAP_FETCH_BATCH_SIZE = int(os.getenv("SITEMAP_FETCH_BATCH_SIZE", "20"))

def _sitemap_default_url(site_url: str) -> str:
    parsed = urlparse(site_url)
    return f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

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
        response = await client.get(robots_url, follow_redirects=True, headers={"User-Agent": choose_user_agent()})
        if response.status_code == 200 and response.text:
            discovered.update(_extract_sitemap_locations_from_robots(response.text))
    except Exception:
        pass

    return sorted(discovered)

async def _fetch_and_parse_sitemap(sitemap_url: str, client: httpx.AsyncClient) -> tuple[str, ET.Element | None]:
    try:
        response = await fetch(client, sitemap_url)
        root = ET.fromstring(response.text)
        return sitemap_url, root
    except Exception as e:
        logger.debug("Could not fetch/parse sitemap %s: %s", sitemap_url, e)
        return sitemap_url, None

async def collect_articles_from_sitemaps(
    outlet_name: str,
    site_url: str,
    client: httpx.AsyncClient,
    days_back: int,
    max_articles: int,
) -> list[dict[str, str]]:
    cutoff_date = datetime.now() - timedelta(days=days_back)
    seeds = await _discover_sitemaps(site_url, client)

    pending_index: set[str] = set(seeds)
    visited: set[str] = set()
    leaf_shard_urls: list[str] = []

    while pending_index and len(visited) < MAX_SITEMAP_URLS_PER_OUTLET:
        batch = list(pending_index - visited)[:_SITEMAP_FETCH_BATCH_SIZE]
        pending_index -= set(batch)
        visited.update(batch)

        results = await asyncio.gather(*[_fetch_and_parse_sitemap(u, client) for u in batch])

        for url, root in results:
            if root is None:
                continue
            root_tag = tag_name(root.tag)
            if root_tag == "sitemapindex":
                for child in root:
                    if tag_name(child.tag) != "sitemap":
                        continue
                    for node in child:
                        if tag_name(node.tag) == "loc" and node.text:
                            loc = node.text.strip()
                            if loc and loc not in visited and is_same_or_subdomain(site_url, loc):
                                pending_index.add(loc)
                            break
            elif root_tag == "urlset":
                leaf_shard_urls.append(url)

    if not leaf_shard_urls:
        logger.debug("[SITEMAP] No leaf shards found for %s", outlet_name)
        return []

    logger.debug("[SITEMAP] %s: %d leaf shards to fetch (visited %d index nodes)", outlet_name, len(leaf_shard_urls), len(visited))

    discovered_articles: dict[str, dict[str, str]] = {}

    for i in range(0, len(leaf_shard_urls), _SITEMAP_FETCH_BATCH_SIZE):
        if len(discovered_articles) >= max_articles:
            break

        batch = leaf_shard_urls[i : i + _SITEMAP_FETCH_BATCH_SIZE]
        results = await asyncio.gather(*[_fetch_and_parse_sitemap(u, client) for u in batch])

        for _url, root in results:
            if root is None or tag_name(root.tag) != "urlset":
                continue

            for child in root:
                if tag_name(child.tag) != "url":
                    continue

                loc = ""
                lastmod_raw = None
                for node in child:
                    tag = tag_name(node.tag)
                    if tag == "loc" and node.text:
                        loc = node.text.strip()
                    elif tag == "lastmod" and node.text:
                        lastmod_raw = node.text.strip()

                if not loc or not is_article_url(loc) or not is_same_or_subdomain(site_url, loc):
                    continue

                pub = parse_metadata_datetime(lastmod_raw)
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
