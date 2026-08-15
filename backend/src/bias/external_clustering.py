from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from .clusterer import TopicClusterSpec


DEFAULT_EXTERNAL_CLUSTER_API_URL = "http://localhost:8000"
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


class ExternalClusteringError(RuntimeError):
    """Raised when the external clustering service cannot provide a valid response."""


class ExternalClusteringNoDataError(ExternalClusteringError):
    """Raised when no external clusters overlap the current local cohort."""


@dataclass(frozen=True)
class ExternalClusterResult:
    clusters: list[TopicClusterSpec]
    mapping_stats: dict[str, Any]


def canonicalize_article_url(raw_url: str | None) -> str:
    """Return a conservative URL identity suitable for joining two article stores."""
    value = (raw_url or "").strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return value.rstrip("/").lower()

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return value.rstrip("/").lower()

    port = parsed.port
    if port and port not in {80, 443}:
        host = f"{host}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_pairs = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_") or normalized_key in TRACKING_QUERY_KEYS:
            continue
        query_pairs.append((key, item_value))
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)

    canonical = f"{host}{path}"
    return f"{canonical}?{query}" if query else canonical


class ExternalClusteringClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_pages: int | None = None,
        max_workers: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv(
            "NEWS_CLUSTER_API_URL", DEFAULT_EXTERNAL_CLUSTER_API_URL
        )).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv(
            "NEWS_CLUSTER_API_TIMEOUT_SECONDS", "30"
        ))
        self.max_pages = max_pages or int(os.getenv("NEWS_CLUSTER_API_MAX_PAGES", "100"))
        self.max_workers = max_workers or int(os.getenv("NEWS_CLUSTER_API_MAX_WORKERS", "8"))
        self._client = client

    def status(self) -> dict[str, Any]:
        try:
            with self._client_context() as client:
                stats = self._get_json(client, "/stats")
            if not isinstance(stats, dict):
                raise ExternalClusteringError("External /stats response was not an object.")
            return {
                "available": True,
                "base_url": self.base_url,
                "stats": stats,
                "error": None,
            }
        except ExternalClusteringError as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "stats": None,
                "error": str(exc),
            }

    def fetch_clusters(self, local_articles: Iterable[Any]) -> ExternalClusterResult:
        local_rows = list(local_articles)
        local_by_url: dict[str, Any] = {}
        local_url_collisions = 0
        for article in local_rows:
            canonical = canonicalize_article_url(getattr(article, "url", None))
            if not canonical:
                continue
            if canonical in local_by_url:
                local_url_collisions += 1
                continue
            local_by_url[canonical] = article

        with self._client_context() as client:
            stats = self._get_json(client, "/stats")
            summaries = self._get_json(client, "/clusters", params={"min_size": 2})
            if not isinstance(stats, dict):
                raise ExternalClusteringError("External /stats response was not an object.")
            if not isinstance(summaries, list):
                raise ExternalClusteringError("External /clusters response was not an array.")

            total_articles = int(stats.get("total_articles") or 0)
            page_size = 100
            total_pages = min(self.max_pages, math.ceil(total_articles / page_size))
            offsets = [page * page_size for page in range(total_pages)]

            def fetch_page(offset: int) -> list[dict[str, Any]]:
                payload = self._get_json(
                    client,
                    "/articles",
                    params={"limit": page_size, "offset": offset},
                )
                if not isinstance(payload, list):
                    raise ExternalClusteringError(
                        f"External /articles response at offset {offset} was not an array."
                    )
                return payload

            pages: list[list[dict[str, Any]]] = []
            if offsets:
                if self.max_workers <= 1 or len(offsets) == 1:
                    pages = [fetch_page(offset) for offset in offsets]
                else:
                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        pages = list(executor.map(fetch_page, offsets))

        external_articles = [article for page in pages for article in page]
        summary_by_id: dict[int, dict[str, Any]] = {}
        for summary in summaries:
            try:
                summary_by_id[int(summary.get("cluster_id"))] = summary
            except (AttributeError, TypeError, ValueError):
                continue

        grouped_local_ids: dict[int, list[int]] = {}
        grouped_seen_ids: dict[int, set[int]] = {}
        matched_local_ids: set[int] = set()
        matched_clustered_local_ids: set[int] = set()

        for external_article in external_articles:
            if not isinstance(external_article, dict):
                continue
            canonical = canonicalize_article_url(external_article.get("url"))
            local_article = local_by_url.get(canonical)
            if local_article is None:
                continue

            local_id = getattr(local_article, "id", None)
            if local_id is None:
                continue
            local_id = int(local_id)
            matched_local_ids.add(local_id)

            cluster_id_raw = external_article.get("cluster_id")
            try:
                cluster_id = int(cluster_id_raw)
            except (TypeError, ValueError):
                continue
            if cluster_id < 0:
                continue

            matched_clustered_local_ids.add(local_id)
            seen = grouped_seen_ids.setdefault(cluster_id, set())
            if local_id in seen:
                continue
            seen.add(local_id)
            grouped_local_ids.setdefault(cluster_id, []).append(local_id)

        clusters: list[TopicClusterSpec] = []
        for cluster_id in sorted(grouped_local_ids):
            article_ids = grouped_local_ids[cluster_id]
            if len(article_ids) < 2:
                continue
            summary = summary_by_id.get(cluster_id, {})
            label = str(summary.get("event_title") or f"External cluster {cluster_id}").strip()
            clusters.append(
                TopicClusterSpec(
                    topic_key=f"sl-news-api:{cluster_id}",
                    topic_label=label,
                    article_ids=article_ids,
                )
            )

        mapping_stats = {
            "local_articles": len(local_rows),
            "local_urls_indexed": len(local_by_url),
            "local_url_collisions": local_url_collisions,
            "external_articles_reported": total_articles,
            "external_articles_fetched": len(external_articles),
            "external_fetch_truncated": total_pages * page_size < total_articles,
            "matched_local_articles": len(matched_local_ids),
            "matched_clustered_local_articles": len(matched_clustered_local_ids),
            "external_clusters_reported": len(summaries),
            "mapped_clusters_with_two_articles": len(clusters),
        }
        return ExternalClusterResult(clusters=clusters, mapping_stats=mapping_stats)

    def _client_context(self):
        if self._client is not None:
            return _BorrowedClientContext(self._client)
        return httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalClusteringError(
                f"External clustering request failed for {path}: {exc}"
            ) from exc


class _BorrowedClientContext:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def __enter__(self) -> httpx.Client:
        return self.client

    def __exit__(self, *_: Any) -> None:
        return None


def get_external_clustering_status() -> dict[str, Any]:
    return ExternalClusteringClient().status()


def fetch_external_clusters(local_articles: Iterable[Any]) -> ExternalClusterResult:
    return ExternalClusteringClient().fetch_clusters(local_articles)
