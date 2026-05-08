from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from api import models

CLUSTER_DISTANCE_THRESHOLD = float(os.getenv("BIAS_CLUSTER_DISTANCE_THRESHOLD", "0.52"))
_CLUSTER_THRESHOLD_EXPLICIT = os.getenv("BIAS_CLUSTER_DISTANCE_THRESHOLD") is not None
MAX_CLUSTER_SIZE = int(os.getenv("BIAS_MAX_CLUSTER_SIZE", "18"))
MIN_CLUSTER_CENTROID_SIMILARITY = float(os.getenv("BIAS_MIN_CLUSTER_CENTROID_SIMILARITY", "0.42"))
MAX_SPLIT_DEPTH = int(os.getenv("BIAS_MAX_SPLIT_DEPTH", "3"))
MIN_TOPIC_OUTLETS = int(os.getenv("BIAS_MIN_TOPIC_OUTLETS", "3"))
MAX_DOMINANT_OUTLET_SHARE = float(os.getenv("BIAS_MAX_DOMINANT_OUTLET_SHARE", "0.6"))
MERGE_SIMILARITY_THRESHOLD = 0.5


@dataclass(frozen=True)
class TopicClusterSpec:
    topic_key: str
    topic_label: str | None
    article_ids: List[int]


def build_internal_clusters(
    embeddings: np.ndarray,
    analysis_articles: List[models.Article],
    run_logs: List[str],
) -> Dict[int, List[int]]:
    if _CLUSTER_THRESHOLD_EXPLICIT:
        threshold = CLUSTER_DISTANCE_THRESHOLD
        run_logs.append(f"Clustering threshold: {threshold:.4f} (explicit env override)")
    else:
        threshold = _adaptive_cluster_threshold(embeddings)
        run_logs.append(
            f"Adaptive clustering threshold: {threshold:.4f} "
            f"(fixed default was {CLUSTER_DISTANCE_THRESHOLD})"
        )

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)
    clusters = _group_by_label(labels)
    clusters = _refine_clusters_for_coherence(clusters, embeddings)
    clusters = _split_outlet_dominated_clusters(clusters, analysis_articles)

    clusters, merge_stats = _merge_single_outlet_clusters(clusters, embeddings, analysis_articles)
    if merge_stats["merged_clusters"]:
        run_logs.append(
            "Merged single-outlet clusters: "
            f"{merge_stats['merged_clusters']} (articles merged: {merge_stats['merged_articles']})"
        )
    return clusters


def normalize_external_clusters(
    clusters: Iterable[Mapping[str, Any] | TopicClusterSpec],
) -> List[TopicClusterSpec]:
    normalized: List[TopicClusterSpec] = []

    for item in clusters:
        if isinstance(item, TopicClusterSpec):
            normalized.append(item)
            continue

        payload: Mapping[str, Any]
        if hasattr(item, "model_dump"):
            payload = item.model_dump()  # type: ignore[assignment]
        elif isinstance(item, Mapping):
            payload = item
        else:
            raise ValueError("Invalid cluster item type.")

        topic_key = str(payload.get("topic_key", "")).strip()
        topic_label_raw = payload.get("topic_label")
        topic_label = str(topic_label_raw).strip() if topic_label_raw else None
        article_ids_raw = payload.get("article_ids", [])
        if not isinstance(article_ids_raw, list):
            raise ValueError("Each cluster must provide article_ids as a list of integers.")

        article_ids: List[int] = []
        seen_ids: Set[int] = set()
        for raw_id in article_ids_raw:
            try:
                article_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if article_id <= 0 or article_id in seen_ids:
                continue
            seen_ids.add(article_id)
            article_ids.append(article_id)

        if not topic_key:
            raise ValueError("Each cluster must provide a non-empty topic_key.")
        if not article_ids:
            raise ValueError(f"Cluster '{topic_key}' has no valid article IDs.")

        normalized.append(
            TopicClusterSpec(
                topic_key=topic_key,
                topic_label=topic_label,
                article_ids=article_ids,
            )
        )

    if not normalized:
        raise ValueError("No clusters provided.")

    return normalized


def build_external_clusters(
    external_clusters: List[TopicClusterSpec],
    analysis_articles: List[models.Article],
) -> Tuple[Dict[int, List[int]], Dict[int, Dict[str, str | None]], int]:
    index_by_article_id: Dict[int, int] = {}
    for idx, article in enumerate(analysis_articles):
        if article.id is not None:
            index_by_article_id[int(article.id)] = idx

    used_article_ids: Set[int] = set()
    clusters: Dict[int, List[int]] = {}
    topic_overrides: Dict[int, Dict[str, str | None]] = {}
    ignored_clusters = 0
    next_label = 0

    for cluster in external_clusters:
        indices: List[int] = []
        for article_id in cluster.article_ids:
            if article_id in used_article_ids:
                continue
            idx = index_by_article_id.get(article_id)
            if idx is None:
                continue
            indices.append(idx)
            used_article_ids.add(article_id)

        if len(indices) < 2:
            ignored_clusters += 1
            continue

        clusters[next_label] = indices
        topic_overrides[next_label] = {
            "topic_key": cluster.topic_key,
            "topic_label": cluster.topic_label,
        }
        next_label += 1

    return clusters, topic_overrides, ignored_clusters


def stable_topic_key(
    cluster_embeddings: np.ndarray,
    articles: List[models.Article],
    indices: List[int],
    n_hash_dims: int = 16,
) -> str:
    """Stable topic key by hashing the quantized cluster centroid.

    Same topic across runs → same key because centroid is rounded to 2 decimal places,
    absorbing minor article turnover. Domain of most-central article namespaces the hash.
    """
    centroid = np.mean(cluster_embeddings, axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 1e-8:
        centroid = centroid / norm

    quantized = np.round(centroid[:n_hash_dims], decimals=2)
    vec_str = ",".join(f"{v:.2f}" for v in quantized)

    sim_matrix = np.dot(cluster_embeddings, cluster_embeddings.T)
    mean_sims = sim_matrix.mean(axis=1)
    central_idx = indices[int(np.argmax(mean_sims))]
    url = getattr(articles[central_idx], "url", "") or ""
    domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    domain = domain_match.group(1).lower() if domain_match else "unknown"

    hex_hash = hashlib.sha256(f"{vec_str}|{domain}".encode()).hexdigest()[:12]
    return f"topic-{hex_hash}"


def dominant_outlet_share(indices: List[int], articles: List[models.Article]) -> float:
    if not indices:
        return 0.0
    counts: Dict[str, int] = {}
    for idx in indices:
        outlet = articles[idx].outlet or ""
        counts[outlet] = counts.get(outlet, 0) + 1
    return max(counts.values()) / len(indices)


def get_dominant_outlet(indices: List[int], articles: List[models.Article]) -> str:
    counts: Dict[str, int] = {}
    for idx in indices:
        outlet = articles[idx].outlet or ""
        counts[outlet] = counts.get(outlet, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _adaptive_cluster_threshold(
    embeddings: np.ndarray,
    sample_size: int = 500,
) -> float:
    """40th-percentile pairwise cosine distance, clamped to [0.30, 0.70].

    Adapts to corpus density: dense news cycles get a tighter threshold.
    """
    n = len(embeddings)
    if n < 4:
        return CLUSTER_DISTANCE_THRESHOLD

    if n > sample_size:
        rng = np.random.default_rng(seed=42)
        indices = rng.choice(n, size=sample_size, replace=False)
        sample = embeddings[indices]
    else:
        sample = embeddings

    sim_matrix = np.dot(sample, sample.T)
    upper = np.triu_indices(len(sample), k=1)
    pairwise_dists = 1.0 - sim_matrix[upper]

    threshold = float(np.percentile(pairwise_dists, 40.0))
    return float(np.clip(threshold, 0.30, 0.70))


def _group_by_label(labels: np.ndarray) -> Dict[int, List[int]]:
    grouped: Dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(idx)
    return grouped


def _refine_clusters_for_coherence(
    clusters: Dict[int, List[int]],
    embeddings: np.ndarray,
) -> Dict[int, List[int]]:
    next_label = max(clusters.keys(), default=-1) + 1
    refined: Dict[int, List[int]] = {}
    for label, indices in clusters.items():
        split_groups = _split_cluster_if_needed(indices, embeddings, depth=0)
        for group in split_groups:
            refined[next_label] = group
            next_label += 1
    return refined


def _split_cluster_if_needed(
    indices: List[int],
    embeddings: np.ndarray,
    depth: int,
) -> List[List[int]]:
    if len(indices) <= 2:
        return [indices]
    if depth >= MAX_SPLIT_DEPTH:
        return [indices]

    cluster_vectors = embeddings[indices]
    centroid = np.mean(cluster_vectors, axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
    sims = np.dot(cluster_vectors, centroid)
    mean_sim = float(np.mean(sims))
    too_large = len(indices) > MAX_CLUSTER_SIZE
    low_coherence = mean_sim < MIN_CLUSTER_CENTROID_SIMILARITY
    if not too_large and not low_coherence:
        return [indices]

    splitter = AgglomerativeClustering(
        n_clusters=2,
        metric="cosine",
        linkage="average",
    )
    local_labels = splitter.fit_predict(cluster_vectors)
    left = [indices[i] for i, lab in enumerate(local_labels) if int(lab) == 0]
    right = [indices[i] for i, lab in enumerate(local_labels) if int(lab) == 1]
    if not left or not right:
        return [indices]

    return _split_cluster_if_needed(left, embeddings, depth + 1) + _split_cluster_if_needed(
        right, embeddings, depth + 1
    )


def _split_outlet_dominated_clusters(
    clusters: Dict[int, List[int]],
    articles: List[models.Article],
) -> Dict[int, List[int]]:
    next_label = max(clusters.keys(), default=-1) + 1
    refined: Dict[int, List[int]] = {}
    for _, indices in clusters.items():
        if not indices:
            continue
        counts: Dict[str, int] = {}
        for idx in indices:
            outlet = articles[idx].outlet or ""
            counts[outlet] = counts.get(outlet, 0) + 1
        dominant_outlet, dominant_count = max(counts.items(), key=lambda item: item[1])
        share = dominant_count / len(indices)

        if share <= MAX_DOMINANT_OUTLET_SHARE or len(indices) < 4:
            refined[next_label] = indices
            next_label += 1
            continue

        dominant_idxs = [idx for idx in indices if (articles[idx].outlet or "") == dominant_outlet]
        other_idxs = [idx for idx in indices if (articles[idx].outlet or "") != dominant_outlet]

        if dominant_idxs and other_idxs:
            refined[next_label] = dominant_idxs
            next_label += 1
            refined[next_label] = other_idxs
            next_label += 1
        else:
            refined[next_label] = indices
            next_label += 1
    return refined


def _merge_single_outlet_clusters(
    clusters: Dict[int, List[int]],
    embeddings: np.ndarray,
    articles: List[models.Article],
) -> Tuple[Dict[int, List[int]], Dict[str, int]]:
    merged_clusters = 0
    merged_articles = 0
    cluster_items: Dict[int, Dict[str, Any]] = {}
    for label, indices in clusters.items():
        outlet_set = {articles[idx].outlet for idx in indices}
        centroid = np.mean(embeddings[indices], axis=0)
        cluster_items[label] = {"indices": list(indices), "outlets": outlet_set, "centroid": centroid}

    labels = list(cluster_items.keys())
    for label in labels:
        item = cluster_items[label]
        outlets = item["outlets"]
        if len(outlets) >= 2:
            continue

        best_label = None
        best_similarity = -1.0
        for candidate_label, candidate in cluster_items.items():
            if candidate_label == label:
                continue
            if outlets.intersection(candidate["outlets"]):
                continue
            similarity = _cosine_similarity(item["centroid"], candidate["centroid"])
            if similarity > best_similarity:
                best_similarity = similarity
                best_label = candidate_label

        if best_label is not None and best_similarity >= MERGE_SIMILARITY_THRESHOLD:
            target = cluster_items[best_label]
            target_indices = target["indices"]
            target_indices.extend(item["indices"])
            target["outlets"] = target["outlets"].union(outlets)
            target["centroid"] = np.mean(embeddings[target_indices], axis=0)
            merged_clusters += 1
            merged_articles += len(item["indices"])
            cluster_items.pop(label, None)

    merged: Dict[int, List[int]] = {
        label: item["indices"] for label, item in cluster_items.items()
    }
    return merged, {"merged_clusters": merged_clusters, "merged_articles": merged_articles}


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    norm_a = vec_a / (np.linalg.norm(vec_a) + 1e-8)
    norm_b = vec_b / (np.linalg.norm(vec_b) + 1e-8)
    return float(np.dot(norm_a, norm_b))
