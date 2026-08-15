from datetime import datetime

import httpx

from api import models
from src.bias.external_clustering import ExternalArticleRecord, ExternalClusteringClient
from src.bias.service import _upsert_external_articles


def test_external_client_loads_cluster_articles_directly():
    body = "A complete external article body about monetary policy. " * 8

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stats":
            return httpx.Response(200, json={"total_articles": 2, "total_clusters": 1})
        if request.url.path == "/sources/builtin":
            return httpx.Response(
                200,
                json=[
                    {"key": "daily_ft", "name": "Daily FT"},
                    {"key": "economynext", "name": "EconomyNext"},
                ],
            )
        if request.url.path == "/clusters":
            return httpx.Response(
                200,
                json=[
                    {
                        "cluster_id": 7,
                        "event_title": "Central bank policy decision",
                        "article_count": 2,
                        "sources": ["daily_ft", "economynext"],
                        "latest_at": "2026-08-15T10:00:00",
                        "category": "economics",
                    }
                ],
            )
        if request.url.path == "/clusters/7":
            return httpx.Response(
                200,
                json={
                    "cluster_id": 7,
                    "event_title": "Central bank policy decision",
                    "article_count": 2,
                    "sources": ["daily_ft", "economynext"],
                    "category": "economics",
                    "articles": [
                        {
                            "id": 1001,
                            "title": "Policy decision",
                            "source": "daily_ft",
                            "url": "https://www.ft.lk/news/policy-decision",
                            "published_at": "2026-08-15T09:00:00",
                            "body": body,
                            "image_url": None,
                        },
                        {
                            "id": 1002,
                            "title": "Policy response",
                            "source": "economynext",
                            "url": "https://economynext.com/policy-response",
                            "published_at": "2026-08-15T08:00:00",
                            "body": body,
                            "image_url": None,
                        },
                    ],
                },
            )
        return httpx.Response(404)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://cluster.test",
    )
    result = ExternalClusteringClient(
        base_url="http://cluster.test",
        client=http_client,
        max_workers=1,
    ).fetch_dataset(
        analysis_type="general",
        since=datetime(2026, 8, 1),
    )

    assert [article.id for article in result.articles] == [1001, 1002]
    assert [article.source for article in result.articles] == ["Daily FT", "Economy Next"]
    assert len(result.clusters) == 1
    assert result.clusters[0].topic_key == "sl-news-api:7"
    assert result.clusters[0].article_ids == [1001, 1002]
    assert result.mapping_stats["external_articles_loaded"] == 2
    assert result.mapping_stats["external_clusters_loaded"] == 1


def test_financial_dataset_requests_economics_clusters():
    requested_category = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_category
        if request.url.path == "/stats":
            return httpx.Response(200, json={"total_articles": 0, "total_clusters": 0})
        if request.url.path == "/sources/builtin":
            return httpx.Response(200, json=[])
        if request.url.path == "/clusters":
            requested_category = request.url.params.get("category")
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://cluster.test",
    )
    ExternalClusteringClient(client=http_client).fetch_dataset(
        analysis_type="financial",
        since=datetime(2026, 8, 1),
    )

    assert requested_category == "economics"


def test_external_status_reports_transport_failure_without_throwing():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "offline"})

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://cluster.test",
    )

    status = ExternalClusteringClient(
        base_url="http://cluster.test",
        client=http_client,
    ).status()

    assert status["available"] is False
    assert status["stats"] is None
    assert "/stats" in status["error"]


def test_cluster_detail_timeouts_are_retried_then_skipped():
    body = "A complete external article body. " * 8
    detail_calls = {7: 0, 8: 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stats":
            return httpx.Response(200, json={"total_articles": 4, "total_clusters": 2})
        if request.url.path == "/sources/builtin":
            return httpx.Response(200, json=[])
        if request.url.path == "/clusters":
            return httpx.Response(
                200,
                json=[
                    {
                        "cluster_id": cluster_id,
                        "event_title": f"Cluster {cluster_id}",
                        "article_count": 2,
                        "sources": ["source_a", "source_b"],
                        "latest_at": "2026-08-15T10:00:00",
                    }
                    for cluster_id in (7, 8)
                ],
            )
        if request.url.path in {"/clusters/7", "/clusters/8"}:
            cluster_id = int(request.url.path.rsplit("/", 1)[1])
            detail_calls[cluster_id] += 1
            if cluster_id == 8 or detail_calls[cluster_id] == 1:
                raise httpx.ReadTimeout("slow cluster", request=request)
            return httpx.Response(
                200,
                json={
                    "cluster_id": 7,
                    "event_title": "Recovered cluster",
                    "articles": [
                        {
                            "id": article_id,
                            "title": f"Article {article_id}",
                            "source": source,
                            "url": f"https://example.test/{article_id}",
                            "published_at": "2026-08-15T09:00:00",
                            "body": body,
                        }
                        for article_id, source in ((71, "source_a"), (72, "source_b"))
                    ],
                },
            )
        return httpx.Response(404)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://cluster.test",
    )
    result = ExternalClusteringClient(
        client=http_client,
        max_workers=1,
        detail_retries=1,
        retry_backoff_seconds=0,
    ).fetch_dataset(analysis_type="general", since=datetime(2026, 8, 1))

    assert [cluster.topic_key for cluster in result.clusters] == ["sl-news-api:7"]
    assert detail_calls == {7: 2, 8: 2}
    assert result.mapping_stats["external_clusters_failed"] == 1
    assert result.mapping_stats["external_failed_cluster_ids"] == [8]


def test_external_article_cache_does_not_touch_internal_articles(mock_db_session):
    record = ExternalArticleRecord(
        id=1001,
        title="External clustered story",
        source="Daily FT",
        published_at=datetime(2026, 8, 15),
        url="https://external.test/story",
        body="A complete article body. " * 10,
        cluster_id=7,
        category="economics",
    )

    rows = _upsert_external_articles(mock_db_session, [record])
    mock_db_session.commit()

    assert [row.id for row in rows] == [1001]
    assert mock_db_session.query(models.ExternalArticle).count() == 1
    assert mock_db_session.query(models.Article).count() == 0
