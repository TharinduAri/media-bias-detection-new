import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

import httpx
import sentry_sdk
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential

from .outlets import (
    AdaDeranaOutlet,
    CeylonTodayOutlet,
    DailyFTOutlet,
    EconomyNextOutlet,
    LBOOutlet,
    NewsfirstOutlet,
    TheMorningOutlet,
    ColomboGazetteOutlet,
    TheIslandOutlet,
    DailyMirrorOutlet,
    DailyNewsOutlet,
    SundayObserverOutlet,
    NewsLKOutlet,
    BaseOutletScraper,
)
from src.collection.core.db import replay_fallback_articles, save_to_db
from src.collection.core.http_client import (
    GhostResponseError, set_semaphore, get_blocked_paths, clear_blocked_paths, record_blocked_path, fetch
)
from src.collection.core.utils import domain_of
from src.collection.core.extraction import extract_with_trafilatura
from src.collection.discovery.sitemap import collect_articles_from_sitemaps
from src.collection.discovery.wordpress import fetch_wordpress_api_payload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.2)

SCRAPE_MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
MAX_CONCURRENT_REQUESTS = 10
MAX_ARTICLES_PER_OUTLET = int(os.getenv("MAX_ARTICLES_PER_OUTLET", "300"))
DAYS_BACK = int(os.getenv("DAYS_BACK", "28"))
SAVE_CHUNK_SIZE = int(os.getenv("SAVE_CHUNK_SIZE", "100"))
OUTLET_DISCOVERY_TIMEOUT_SECONDS = int(os.getenv("OUTLET_DISCOVERY_TIMEOUT_SECONDS", "300"))
ARTICLE_SCRAPE_TIMEOUT_SECONDS = int(os.getenv("ARTICLE_SCRAPE_TIMEOUT_SECONDS", "25"))
STRICT_RECENT_ONLY = os.getenv("STRICT_RECENT_ONLY", "true").strip().lower() == "true"


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
        blocked_paths = get_blocked_paths()
        blocked_total = len(blocked_paths)
        logging.info(
            "[RUN SUMMARY] Duration: %dm%ds | Outlets: %d | Success: %d | Failed: %d (%s)\n"
            "              URLs discovered: %d | Parse errors: %d | Persisted: %d\n"
            "              Ghost responses skipped: %d | 403 Blocked paths: %d%s",
            duration_s // 60, duration_s % 60,
            len(self.outlet_stats), success_count, len(failed), failed_detail,
            self.total_discovered, self.parse_errors, self.total_persisted,
            ghost_total, blocked_total,
            ("\n              Blocked: " + ", ".join(sorted(blocked_paths))) if blocked_paths else "",
        )


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
    if isinstance(exc, (PermissionError, GhostResponseError)):
        return False

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 403:
            try:
                blocked_path = str(exc.response.url)
            except Exception:
                blocked_path = "unknown"
            record_blocked_path(blocked_path)
            logging.debug("403 Forbidden — blocked path recorded: %s", blocked_path)
            return False
        return status >= 500 or status == 429

    return True


def _parse_article_datetime(raw_date: object) -> datetime | None:
    if raw_date is None:
        return None
    text = str(raw_date).strip()
    if not text:
        return None

    iso_candidates = [text]
    if text.endswith("Z"):
        iso_candidates.append(text[:-1] + "+00:00")

    for candidate in iso_candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    known_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in known_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def _extract_adaderana_nid(url: str) -> int | None:
    if not url:
        return None
    patterns = [
        r"[?&]nid=(\d+)",
        r"/news/(\d+)/",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _filter_adaderana_legacy_urls(outlet_name: str, articles: list[dict[str, str]]) -> list[dict[str, str]]:
    if outlet_name.strip().lower() not in {"ada derana", "adaderana"}:
        return articles

    nids = [
        nid for nid in (_extract_adaderana_nid(str(article.get("url", ""))) for article in articles)
        if nid is not None
    ]
    if not nids:
        return articles

    max_nid = max(nids)
    min_allowed = max_nid - 3000
    filtered: list[dict[str, str]] = []
    dropped = 0
    for article in articles:
        nid = _extract_adaderana_nid(str(article.get("url", "")))
        if nid is None or nid >= min_allowed:
            filtered.append(article)
        else:
            dropped += 1

    if dropped:
        logging.info(
            "[%s] URL-range filter dropped %d legacy URLs (nid < %d, latest nid=%d)",
            outlet_name, dropped, min_allowed, max_nid,
        )
    return filtered


_OUTLETS: list[dict[str, str]] = [
    # Specialist scrapers (matched by domain in _OUTLET_REGISTRY below)
    {"name": "Ada Derana",       "url": "https://www.adaderana.lk"},
    {"name": "Ceylon Today",     "url": "https://www.ceylontoday.lk"},
    {"name": "Daily FT",         "url": "https://www.ft.lk"},
    {"name": "Economy Next",     "url": "https://economynext.com"},
    {"name": "LBO",              "url": "https://www.lankabusinessonline.com"},
    {"name": "Newsfirst",        "url": "https://english.newsfirst.lk"},
    {"name": "Daily Mirror",     "url": "https://www.dailymirror.lk"},
    {"name": "The Morning",      "url": "https://www.themorning.lk"},
    {"name": "Daily News",       "url": "https://www.dailynews.lk"},
    {"name": "The Island",       "url": "https://island.lk"},
    {"name": "Sunday Observer",  "url": "https://www.sundayobserver.lk"},
    {"name": "Colombo Gazette",  "url": "https://colombogazette.com"},
    {"name": "News LK",          "url": "https://www.news.lk"},
]

_OUTLET_REGISTRY: list[tuple[tuple[str, ...], type[BaseOutletScraper]]] = [
    (("adaderana.lk",),                            AdaDeranaOutlet),
    (("ceylontoday.lk",),                          CeylonTodayOutlet),
    (("ft.lk", "dailyft.lk"),                      DailyFTOutlet),
    (("economynext.com",),                         EconomyNextOutlet),
    (("lbo.lk", "lankabusinessonline.com"),        LBOOutlet),
    (("newsfirst.lk", "english.newsfirst.lk"),     NewsfirstOutlet),
    (("themorning.lk",),                           TheMorningOutlet),
    (("colombogazette.com",),                      ColomboGazetteOutlet),
    (("island.lk",),                               TheIslandOutlet),
    (("dailymirror.lk",),                          DailyMirrorOutlet),
    (("dailynews.lk",),                            DailyNewsOutlet),
    (("sundayobserver.lk",),                       SundayObserverOutlet),
    (("news.lk",),                                 NewsLKOutlet),
]


def _build_outlet_scraper(name: str, url: str) -> BaseOutletScraper:
    domain = domain_of(url).lstrip("www.").lower()
    for suffixes, cls in _OUTLET_REGISTRY:
        if any(domain == s or domain.endswith(f".{s}") for s in suffixes):
            logging.debug("[ROUTER] %s → %s", name, cls.__name__)
            return cls(name=name, url=url)

    logging.debug("[ROUTER] %s → GenericOutlet (no specific scraper registered)", name)

    class _GenericOutlet(BaseOutletScraper):
        async def discover_urls(self, client, days_back, max_articles):
            return await collect_articles_from_sitemaps(
                self.name, self.url, client,
                days_back=days_back, max_articles=max_articles,
            )

    return _GenericOutlet(name=name, url=url)


async def process_outlet(outlet: dict[str, str], client: httpx.AsyncClient, days_back: int) -> list[dict[str, str]]:
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
    outlet_articles = _filter_adaderana_legacy_urls(outlet_name, outlet_articles)

    # Date filter safety net catches any articles that outlet-level scrapers
    # failed to filter by date themselves.
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    filtered: list[dict[str, str]] = []
    skipped_old = 0
    skipped_unknown = 0
    for article in outlet_articles:
        parsed_date = _parse_article_datetime(article.get("date"))
        if parsed_date is None:
            if STRICT_RECENT_ONLY:
                skipped_unknown += 1
                continue
        elif parsed_date < cutoff:
            skipped_old += 1
            continue
        filtered.append(article)
    if skipped_old:
        logging.info(
            "[%s] Date filter dropped %d articles older than %d days",
            outlet_name, skipped_old, days_back,
        )
    if skipped_unknown:
        logging.info(
            "[%s] Date filter dropped %d articles with unknown/unparseable date (strict mode)",
            outlet_name, skipped_unknown,
        )
    outlet_articles = filtered

    for art in outlet_articles:
        art.setdefault("_site_url", site_url)

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


@retry(
    stop=stop_after_attempt(SCRAPE_MAX_RETRIES),
    wait=wait_exponential(multiplier=1.5, min=1.5, max=6),
    retry=retry_if_exception(_is_retryable_exception),
    before_sleep=_log_retry_before_sleep,
    retry_error_callback=_scrape_payload_retry_error_callback,
    reraise=False,
)
async def scrape_article_payload(url: str, client: httpx.AsyncClient) -> dict[str, str]:
    wp_payload = await fetch_wordpress_api_payload(url, client)
    if wp_payload is not None:
        return wp_payload

    response = await fetch(client, url)
    raw_html = response.text

    return extract_with_trafilatura(raw_html, url)


async def collect_data(days_back=DAYS_BACK, target_outlet: str | None = None):
    all_articles: list[dict[str, str]] = []
    run = _RunSummary()
    clear_blocked_paths()
    outlets: list[dict[str, str]] = list(_OUTLETS)
    if target_outlet:
        outlets = [o for o in outlets if o["name"].lower() == target_outlet.lower()]
        if not outlets:
            logging.warning("No outlet found matching: %s", target_outlet)
            return

    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    set_semaphore(sem)
    
    await asyncio.to_thread(replay_fallback_articles)

    try:
        timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:

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

            deduped_global: dict[str, dict[str, str]] = {}
            for article in all_articles:
                url = article.get("url")
                if isinstance(url, str) and url and url not in deduped_global:
                    deduped_global[url] = article
            all_articles = list(deduped_global.values())
            run.total_discovered = len(all_articles)

            logging.info("Scraping full content for %d articles concurrently...", len(all_articles))
            total_articles = len(all_articles)

            async def process_article(article: dict[str, str]) -> dict[str, str]:
                url = article["url"]
                outlet_name = article.get("outlet", "")
                site_url = article.get("_site_url", "")

                payload: dict[str, str] | None = None
                scraper_error: Exception | None = None

                if site_url:
                    try:
                        scraper = _build_outlet_scraper(outlet_name, site_url)
                        payload = await asyncio.wait_for(
                            scraper.extract_content(url, client),
                            timeout=float(ARTICLE_SCRAPE_TIMEOUT_SECONDS),
                        )
                    except Exception as exc:
                        scraper_error = exc

                if payload is None:
                    try:
                        payload = await asyncio.wait_for(
                            scrape_article_payload(url, client),
                            timeout=float(ARTICLE_SCRAPE_TIMEOUT_SECONDS),
                        )
                    except Exception:
                        if scraper_error is not None:
                            raise scraper_error
                        raise

                processed = dict(article)
                processed.pop("_site_url", None)
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
            stale_count = 0
            unknown_date_count = 0
            chunk_buffer: list[dict[str, str]] = []
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

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
                parsed_date = _parse_article_datetime(result.get("date"))
                if parsed_date is None:
                    if STRICT_RECENT_ONLY:
                        unknown_date_count += 1
                        continue
                elif parsed_date < cutoff:
                    stale_count += 1
                    continue

                chunk_buffer.append(result)
                valid_count += 1

                if len(chunk_buffer) >= SAVE_CHUNK_SIZE:
                    chunk = chunk_buffer[:SAVE_CHUNK_SIZE]
                    del chunk_buffer[:SAVE_CHUNK_SIZE]
                    await asyncio.to_thread(save_to_db, chunk)

            if ghost_count:
                logging.debug("Total ghost responses during scrape: %d", ghost_count)
                for stat in run.outlet_stats:
                    if not stat.failed:
                        stat.ghost_count = ghost_count // max(1, len(run.outlet_stats))

            run.parse_errors = failed_count

            if failed_count:
                logging.warning(
                    "%d articles failed during content scraping and were skipped", failed_count
                )
            if stale_count:
                logging.info("Dropped %d scraped articles older than %d days", stale_count, days_back)
            if unknown_date_count:
                logging.info(
                    "Dropped %d scraped articles with unknown/unparseable date (strict mode)",
                    unknown_date_count,
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
        set_semaphore(None) # type: ignore # Clear


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the media scraper.")
    parser.add_argument("--outlet", type=str, help="Target outlet name to scrape")
    parser.add_argument("--days-back", type=int, default=DAYS_BACK, help="Number of days to look back for articles")
    args = parser.parse_args()

    try:
        asyncio.run(collect_data(days_back=args.days_back, target_outlet=args.outlet))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise

