from types import SimpleNamespace

import httpx

from src.bias.external_clustering import (
    ExternalClusteringClient,
    canonicalize_article_url,
)


def test_canonicalize_article_url_ignores_safe_transport_and_tracking_differences():
    left = "https://www.ft.lk/news/example-story/?utm_source=newsletter&fbclid=abc"
    right = "http://ft.lk/news/example-story"

    assert canonicalize_article_url(left) == canonicalize_article_url(right)


def test_canonicalize_article_url_preserves_meaningful_query_values():
    assert canonicalize_article_url("https://example.com/story?id=2") != canonicalize_article_url(
        "https://example.com/story?id=3"
    )


def test_external_client_maps_external_urls_to_local_article_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stats":
            return httpx.Response(200, json={"total_articles": 4, "total_clusters": 1})
        if request.url.path == "/clusters":
            return httpx.Response(
                200,
                json=[
                    {
                        "cluster_id": 7,
                        "event_title": "Central bank policy decision",
                        "article_count": 3,
                        "sources": ["daily_ft", "economynext"],
                    }
                ],
            )
        if request.url.path == "/articles":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1001,
                        "url": "https://www.ft.lk/news/policy-decision/",
                        "cluster_id": 7,
                    },
                    {
                        "id": 1002,
                        "url": "http://economynext.com/policy-response?utm_source=social",
                        "cluster_id": 7,
                    },
                    {
                        "id": 1003,
                        "url": "https://external.example/unmatched",
                        "cluster_id": 7,
                    },
                    {
                        "id": 1004,
                        "url": "https://external.example/unclustered",
                        "cluster_id": -1,
                    },
                ],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="http://cluster.test")
    local_articles = [
        SimpleNamespace(id=41, url="http://ft.lk/news/policy-decision"),
        SimpleNamespace(id=84, url="https://www.economynext.com/policy-response"),
        SimpleNamespace(id=99, url="https://local.example/other"),
    ]

    result = ExternalClusteringClient(
        base_url="http://cluster.test",
        client=http_client,
        max_workers=1,
    ).fetch_clusters(local_articles)

    assert len(result.clusters) == 1
    assert result.clusters[0].topic_key == "sl-news-api:7"
    assert result.clusters[0].topic_label == "Central bank policy decision"
    assert result.clusters[0].article_ids == [41, 84]
    assert result.mapping_stats["matched_local_articles"] == 2
    assert result.mapping_stats["matched_clustered_local_articles"] == 2
    assert result.mapping_stats["mapped_clusters_with_two_articles"] == 1


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
