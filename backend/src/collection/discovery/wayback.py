import logging
from datetime import datetime, timedelta, timezone
import httpx

from src.collection.core.utils import domain_of, is_same_or_subdomain, is_article_url

logger = logging.getLogger(__name__)

WAYBACK_ENABLED_DOMAINS = {"adaderana.lk", "dailymirror.lk"}

def looks_like_wayback_target(domain: str) -> bool:
    normalized = domain.lstrip("www.")
    return any(normalized == d or normalized.endswith(f".{d}") for d in WAYBACK_ENABLED_DOMAINS)

async def collect_wayback_urls(
    outlet_name: str,
    site_url: str,
    client: httpx.AsyncClient,
    days_back: int,
    max_articles: int,
) -> list[dict[str, str]]:
    domain = domain_of(site_url)
    if not looks_like_wayback_target(domain):
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
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        response.raise_for_status()
        rows = response.json()
    except Exception as e:
        logger.info("[WAYBACK] Lookup unavailable for %s: %s", outlet_name, e)
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
        if not is_same_or_subdomain(site_url, original_url):
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
