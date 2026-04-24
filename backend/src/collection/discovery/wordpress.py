import logging
from datetime import datetime
from urllib.parse import urlparse
import httpx

from src.collection.core.utils import domain_of, strip_html, parse_metadata_datetime

logger = logging.getLogger(__name__)

WORDPRESS_API_ENABLED_DOMAINS = {"lankabusinessonline.com", "lbo.lk"}

def looks_like_wordpress_api_target(domain: str) -> bool:
    normalized = domain.lstrip("www.")
    return any(normalized == d or normalized.endswith(f".{d}") for d in WORDPRESS_API_ENABLED_DOMAINS)

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
    markers = ("[...]", "[...]", "[&hellip;]", "...", "...", "continue reading", "read more")
    return any(candidate.endswith(marker) for marker in markers)

async def fetch_wordpress_api_payload(url: str, client: httpx.AsyncClient) -> dict[str, str] | None:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if not looks_like_wordpress_api_target(domain):
        return None

    slug = _extract_slug_from_article_url(url)
    if not slug or slug.isdigit():
        return None

    endpoint = f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts"
    params = {"slug": slug, "_fields": "id,date,title,link,content", "per_page": "1"}

    try:
        response = await client.get(
            endpoint,
            params=params,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        response.raise_for_status()
        posts = response.json()
    except Exception as e:
        logger.debug(f"WordPress API lookup failed for {url}: {e}")
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
    extracted_text = strip_html(raw_html)
    if len(extracted_text) < 50 or _looks_truncated_wp_text(extracted_text):
        return None

    published = parse_metadata_datetime(post.get("date"))
    cleaned_title = strip_html(title_html)
    return {
        "raw_html": raw_html,
        "text": extracted_text,
        "title": cleaned_title,
        "date": (published or datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
    }
