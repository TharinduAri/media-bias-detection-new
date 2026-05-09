from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from api import models
from src.bias.clusterer import (
    dominant_outlet_share,
    stable_topic_key,
)


def _articles(outlets: list[str]) -> list:
    articles = []
    for i, outlet in enumerate(outlets):
        a = MagicMock(spec=models.Article)
        a.outlet = outlet
        a.url = f"http://{outlet.lower().replace(' ', '')}.com/{i}"
        articles.append(a)
    return articles


# ── dominant_outlet_share ─────────────────────────────────────────────────────

def test_dominant_share_equal_distribution():
    articles = _articles(["A", "A", "B", "B", "C", "C"])
    share = dominant_outlet_share([0, 1, 2, 3, 4, 5], articles)
    assert share == pytest.approx(2 / 6, abs=1e-6)


def test_dominant_share_single_dominant():
    articles = _articles(["A", "A", "A", "A", "B"])
    share = dominant_outlet_share([0, 1, 2, 3, 4], articles)
    assert share == pytest.approx(4 / 5, abs=1e-6)


def test_dominant_share_all_same_outlet():
    articles = _articles(["X", "X", "X"])
    share = dominant_outlet_share([0, 1, 2], articles)
    assert share == pytest.approx(1.0, abs=1e-6)


def test_dominant_share_empty_indices():
    articles = _articles(["A", "B"])
    share = dominant_outlet_share([], articles)
    assert share == 0.0


def test_dominant_share_single_article():
    articles = _articles(["A"])
    share = dominant_outlet_share([0], articles)
    assert share == pytest.approx(1.0, abs=1e-6)


# ── stable_topic_key ──────────────────────────────────────────────────────────

def _make_embeddings(n: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, 768)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / (norms + 1e-8)


def test_stable_topic_key_format():
    embs = _make_embeddings(5)
    articles = _articles(["A", "B", "C", "A", "B"])
    key = stable_topic_key(embs, articles, [0, 1, 2, 3, 4])
    assert isinstance(key, str)
    assert key.startswith("topic-")


def test_stable_topic_key_deterministic():
    embs = _make_embeddings(5)
    articles = _articles(["A", "B", "C", "A", "B"])
    indices = [0, 1, 2, 3, 4]
    key1 = stable_topic_key(embs, articles, indices)
    key2 = stable_topic_key(embs, articles, indices)
    assert key1 == key2


def test_stable_topic_key_differs_for_different_embeddings():
    embs1 = _make_embeddings(5, seed=1)
    embs2 = _make_embeddings(5, seed=2)
    articles = _articles(["A", "B", "C", "A", "B"])
    key1 = stable_topic_key(embs1, articles, [0, 1, 2, 3, 4])
    key2 = stable_topic_key(embs2, articles, [0, 1, 2, 3, 4])
    assert key1 != key2
