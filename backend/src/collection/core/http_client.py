import asyncio
import logging
import random
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .utils import (
    MIN_DELAY_SECONDS, MAX_DELAY_SECONDS, choose_user_agent, domain_of
)

logger = logging.getLogger(__name__)
_FETCH_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_FETCH_MAX_ATTEMPTS = 3

class GhostResponseError(Exception):
    """Server returned HTTP 200 with a near-empty body — anti-scraping ghosting."""

class DiscoveryError(Exception):
    """Fatal failure during URL discovery for this outlet."""


_REQUEST_SEMAPHORE: asyncio.Semaphore | None = None
_DOMAIN_LOCKS: dict[str, asyncio.Lock] = {}
_DOMAIN_LAST_REQUEST_AT: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, RobotFileParser] = {}
_BLOCKED_PATHS: set[str] = set()


def set_semaphore(sem: asyncio.Semaphore) -> None:
    """Called by the orchestrator once the event-loop semaphore is created."""
    global _REQUEST_SEMAPHORE
    _REQUEST_SEMAPHORE = sem

def get_blocked_paths() -> set[str]:
    return _BLOCKED_PATHS

def clear_blocked_paths() -> None:
    _BLOCKED_PATHS.clear()

def record_blocked_path(path: str) -> None:
    _BLOCKED_PATHS.add(path)


def _domain_lock(domain: str) -> asyncio.Lock:
    if domain not in _DOMAIN_LOCKS:
        _DOMAIN_LOCKS[domain] = asyncio.Lock()
    return _DOMAIN_LOCKS[domain]


async def throttle_domain(domain: str) -> None:
    lock = _domain_lock(domain)
    async with lock:
        now = time.monotonic()
        last = _DOMAIN_LAST_REQUEST_AT.get(domain, 0.0)
        
        # Enforce at least 2.0s delay across all domains to prevent 403/503 blocks under high load
        min_delay = max(2.0, MIN_DELAY_SECONDS)
        max_delay = max(min_delay, MAX_DELAY_SECONDS)
        
        jitter = random.uniform(min_delay, max_delay)
        wait_for = max(0.0, (last + jitter) - now)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        _DOMAIN_LAST_REQUEST_AT[domain] = time.monotonic()


async def load_robots_parser(client: httpx.AsyncClient, url: str) -> RobotFileParser:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    cached = _ROBOTS_CACHE.get(domain)
    if cached is not None:
        return cached

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        response = await client.get(robots_url, follow_redirects=True, headers={"User-Agent": choose_user_agent()})
        if response.status_code == 200 and response.text:
            rp.parse(response.text.splitlines())
    except Exception:
        pass

    _ROBOTS_CACHE[domain] = rp
    return rp


async def can_fetch_url(client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
    try:
        rp = await load_robots_parser(client, url)
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


async def fetch(client: httpx.AsyncClient, url: str, *,
                follow_redirects: bool = True,
                extra_headers: dict[str, str] | None = None) -> httpx.Response:
    """Throttled, robots-compliant GET with semaphore gating."""
    domain = domain_of(url)
    await throttle_domain(domain)

    user_agent = choose_user_agent()
    if not await can_fetch_url(client, url, user_agent):
        raise PermissionError(f"Blocked by robots.txt: {url}")

    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)

    sem = _REQUEST_SEMAPHORE
    last_exc: Exception | None = None

    for attempt in range(1, _FETCH_MAX_ATTEMPTS + 1):
        try:
            if sem:
                async with sem:
                    response = await client.get(url, follow_redirects=follow_redirects, headers=headers)
            else:
                response = await client.get(url, follow_redirects=follow_redirects, headers=headers)

            if response.status_code in _FETCH_RETRYABLE_STATUSES and attempt < _FETCH_MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)
                continue

            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if status not in _FETCH_RETRYABLE_STATUSES:
                    raise
            if attempt >= _FETCH_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(0.5 * attempt)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Failed to fetch URL: {url}")


async def fetch_xml(client: httpx.AsyncClient, url: str) -> ET.Element | None:
    """Fetch and parse an XML document; returns None on any failure."""
    try:
        resp = await fetch(client, url)
        return ET.fromstring(resp.text)
    except Exception as exc:
        logger.debug("XML fetch failed for %s: %s", url, exc)
        return None
