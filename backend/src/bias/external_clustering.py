from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .clusterer import TopicClusterSpec


DEFAULT_EXTERNAL_CLUSTER_API_URL = "http://localhost:8000"
SOURCE_NAME_OVERRIDES = {
    "adaderana": "Ada Derana",
    "ceylon_today": "Ceylon Today",
    "daily_ft": "Daily FT",
    "economynext": "Economy Next",
    "lankabusinessonline": "LBO",
    "newsfirst": "Newsfirst",
}


class ExternalClusteringError(RuntimeError):
    """Raised when the external clustering service cannot provide a valid response."""


class ExternalClusteringNoDataError(ExternalClusteringError):
    """Raised when the external service has no usable clustered articles."""


@dataclass(frozen=True)
class ExternalArticleRecord:
    id: int
    title: str
    source: str
    published_at: datetime | None
    url: str
    body: str
    cluster_id: int
    category: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class ExternalDatasetResult:
    articles: list[ExternalArticleRecord]
    clusters: list[TopicClusterSpec]
    mapping_stats: dict[str, Any]


class ExternalClusteringClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_workers: int | None = None,
        detail_timeout_seconds: float | None = None,
        detail_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv(
            "NEWS_CLUSTER_API_URL", DEFAULT_EXTERNAL_CLUSTER_API_URL
        )).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv(
            "NEWS_CLUSTER_API_TIMEOUT_SECONDS", "30"
        ))
        self.max_workers = max_workers or int(os.getenv("NEWS_CLUSTER_API_MAX_WORKERS", "8"))
        self.detail_timeout_seconds = detail_timeout_seconds or float(os.getenv(
            "NEWS_CLUSTER_API_DETAIL_TIMEOUT_SECONDS", "60"
        ))
        self.detail_retries = (
            detail_retries
            if detail_retries is not None
            else int(os.getenv("NEWS_CLUSTER_API_DETAIL_RETRIES", "2"))
        )
        self.retry_backoff_seconds = (
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else float(os.getenv("NEWS_CLUSTER_API_RETRY_BACKOFF_SECONDS", "1"))
        )
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

    def fetch_dataset(
        self,
        analysis_type: str = "general",
        since: datetime | None = None,
    ) -> ExternalDatasetResult:
        """Fetch external cluster details and their full articles without local joins."""
        cluster_params: dict[str, Any] = {"min_size": 2}
        if (analysis_type or "").strip().lower() == "financial":
            cluster_params["category"] = "economics"

        with self._client_context() as client:
            stats = self._get_json(client, "/stats")
            summaries = self._get_json(client, "/clusters", params=cluster_params)
            builtin_sources = self._get_json(client, "/sources/builtin")
            if not isinstance(stats, dict):
                raise ExternalClusteringError("External /stats response was not an object.")
            if not isinstance(summaries, list):
                raise ExternalClusteringError("External /clusters response was not an array.")
            if not isinstance(builtin_sources, list):
                builtin_sources = []

            current_summaries = []
            for summary in summaries:
                if not isinstance(summary, dict):
                    continue
                sources = {
                    str(source).strip()
                    for source in (summary.get("sources") or [])
                    if str(source).strip()
                }
                if len(sources) < 2:
                    continue
                latest_at = _parse_datetime(summary.get("latest_at"))
                if since is not None and latest_at is not None and latest_at < since:
                    continue
                current_summaries.append(summary)

            def fetch_detail(
                summary: dict[str, Any],
            ) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
                try:
                    cluster_id = int(summary.get("cluster_id"))
                except (TypeError, ValueError) as exc:
                    raise ExternalClusteringError("External cluster is missing a valid ID.") from exc

                last_error: str | None = None
                for attempt in range(self.detail_retries + 1):
                    try:
                        payload = self._get_json(
                            client,
                            f"/clusters/{cluster_id}",
                            timeout_seconds=self.detail_timeout_seconds,
                        )
                        if not isinstance(payload, dict):
                            raise ExternalClusteringError(
                                f"External cluster {cluster_id} response was not an object."
                            )
                        return summary, payload, None
                    except ExternalClusteringError as exc:
                        last_error = str(exc)
                        if attempt < self.detail_retries and self.retry_backoff_seconds > 0:
                            time.sleep(self.retry_backoff_seconds * (2 ** attempt))
                return summary, None, last_error

            if self.max_workers <= 1 or len(current_summaries) <= 1:
                detail_results = [fetch_detail(summary) for summary in current_summaries]
            else:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    detail_results = list(executor.map(fetch_detail, current_summaries))

        details: list[tuple[dict[str, Any], dict[str, Any]]] = []
        failed_cluster_ids: list[int] = []
        failed_cluster_errors: dict[str, str] = {}
        for summary, detail, error in detail_results:
            if detail is not None:
                details.append((summary, detail))
                continue
            cluster_id = int(summary.get("cluster_id"))
            failed_cluster_ids.append(cluster_id)
            failed_cluster_errors[str(cluster_id)] = error or "Unknown cluster detail error"

        source_names = {
            str(item.get("key")): str(item.get("name"))
            for item in builtin_sources
            if isinstance(item, dict) and item.get("key") and item.get("name")
        }
        source_names.update(SOURCE_NAME_OVERRIDES)

        article_by_id: dict[int, ExternalArticleRecord] = {}
        clusters: list[TopicClusterSpec] = []
        articles_without_body = 0
        articles_outside_window = 0

        for summary, detail in details:
            try:
                cluster_id = int(detail.get("cluster_id", summary.get("cluster_id")))
            except (TypeError, ValueError):
                continue
            cluster_article_ids: list[int] = []
            for item in detail.get("articles") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    article_id = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                published_at = _parse_datetime(item.get("published_at"))
                if since is not None and published_at is not None and published_at < since:
                    articles_outside_window += 1
                    continue
                body = str(item.get("body") or "").strip()
                if len(body) <= 100:
                    articles_without_body += 1
                    continue
                source_key = str(item.get("source") or "unknown").strip()
                record = ExternalArticleRecord(
                    id=article_id,
                    title=str(item.get("title") or "Untitled").strip(),
                    source=source_names.get(source_key, source_key.replace("_", " ").title()),
                    published_at=published_at,
                    url=str(item.get("url") or "").strip(),
                    body=body,
                    cluster_id=cluster_id,
                    category=str(detail.get("category") or summary.get("category") or "").strip() or None,
                    image_url=str(item.get("image_url") or "").strip() or None,
                )
                article_by_id[article_id] = record
                cluster_article_ids.append(article_id)

            cluster_article_ids = list(dict.fromkeys(cluster_article_ids))
            if len(cluster_article_ids) < 2:
                continue
            label = str(
                detail.get("event_title")
                or summary.get("event_title")
                or f"External cluster {cluster_id}"
            ).strip()
            clusters.append(
                TopicClusterSpec(
                    topic_key=f"sl-news-api:{cluster_id}",
                    topic_label=label,
                    article_ids=cluster_article_ids,
                )
            )

        used_article_ids = {
            article_id
            for cluster in clusters
            for article_id in cluster.article_ids
        }
        articles = [article_by_id[article_id] for article_id in sorted(used_article_ids)]
        mapping_stats = {
            "external_articles_reported": int(stats.get("total_articles") or 0),
            "external_clusters_reported": len(summaries),
            "external_clusters_in_window": len(current_summaries),
            "external_clusters_loaded": len(clusters),
            "external_articles_loaded": len(articles),
            "external_articles_without_body": articles_without_body,
            "external_articles_outside_window": articles_outside_window,
            "external_clusters_failed": len(failed_cluster_ids),
            "external_failed_cluster_ids": failed_cluster_ids,
            "external_failed_cluster_errors": failed_cluster_errors,
        }
        return ExternalDatasetResult(
            articles=articles,
            clusters=clusters,
            mapping_stats=mapping_stats,
        )

    def _client_context(self):
        if self._client is not None:
            return _BorrowedClientContext(self._client)
        return httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        try:
            response = client.get(path, params=params, timeout=timeout_seconds or self.timeout_seconds)
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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def get_external_clustering_status() -> dict[str, Any]:
    return ExternalClusteringClient().status()


def fetch_external_dataset(
    analysis_type: str,
    since: datetime,
) -> ExternalDatasetResult:
    return ExternalClusteringClient().fetch_dataset(analysis_type=analysis_type, since=since)
