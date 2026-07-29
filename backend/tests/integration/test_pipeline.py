from __future__ import annotations

"""End-to-end pipeline integration test.

All heavy external dependencies (real DB, ML models, Gemini API, embeddings)
are replaced with deterministic mocks so the test is fast and hermetic.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import models
from api.database import Base
from src.bias.models_manager import SentimentResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_article(id_: int, outlet: str, title: str, topic: str) -> models.Article:
    a = models.Article(
        id=id_,
        outlet=outlet,
        title=title,
        text=f"This article is about {topic}. " * 40,
        clean_text=f"This article is about {topic}. " * 40,
        sentences=[f"Sentence {i} about {topic}." for i in range(10)],
        entities=[{"text": f"Entity{i}", "label": "ORG"} for i in range(3)],
        url=f"http://{outlet.lower().replace(' ', '')}.com/{topic}/{id_}",
        date=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    return a


@pytest.fixture
def seeded_articles(db_session) -> List[models.Article]:
    """Insert 30 articles: 3 outlets × 2 topics × 5 articles each."""
    outlets = ["Outlet A", "Outlet B", "Outlet C"]
    topics = [
        ("Politics", "Election results announced"),
        ("Economy", "Central bank raises rates"),
    ]
    articles = []
    idx = 1
    for outlet in outlets:
        for topic_name, base_title in topics:
            for i in range(5):
                a = _make_article(idx, outlet, f"{base_title} — {i+1}", topic_name)
                db_session.add(a)
                articles.append(a)
                idx += 1
    db_session.commit()
    return articles


def _deterministic_embeddings(n_articles: int, dims: int = 768, seed: int = 42) -> np.ndarray:
    """Generate unit-norm embeddings with two clear clusters."""
    rng = np.random.default_rng(seed)
    # Half articles cluster around centroid A, half around B
    half = n_articles // 2
    centroid_a = rng.standard_normal(dims).astype(np.float32)
    centroid_b = rng.standard_normal(dims).astype(np.float32)
    centroid_a /= np.linalg.norm(centroid_a)
    centroid_b /= np.linalg.norm(centroid_b)

    vecs = []
    for i in range(n_articles):
        base = centroid_a if i < half else centroid_b
        noise = rng.standard_normal(dims).astype(np.float32) * 0.05
        v = base + noise
        v /= np.linalg.norm(v)
        vecs.append(v)
    return np.array(vecs, dtype=np.float32)


# ── Integration test ──────────────────────────────────────────────────────────

def test_full_pipeline_end_to_end(db_session, seeded_articles):
    """Run _run_bias_analysis_impl() with all external I/O mocked."""
    n = len(seeded_articles)
    embeddings = _deterministic_embeddings(n)

    # Build analysis_rows structure that load_analysis_rows would return
    analysis_rows = [
        {
            "article": a,
            "text": a.clean_text or a.text or "",
        }
        for a in seeded_articles
    ]

    mock_manager = MagicMock()
    mock_manager.embedding_model_name = "all-mpnet-base-v2"
    mock_manager.sentiment_model_name = "models/deberta-v3-newsmtsc"
    mock_manager.analyze_sentiment.return_value = [
        SentimentResult(
            label="neutral",
            confidence=0.8,
            score=float(i % 3) * 0.1 - 0.1,
            entity_sentiments=[
                {
                    "target": "Entity0",
                    "label": "neutral",
                    "score": 0.0,
                    "confidence": 0.8,
                }
            ],
            target_pair_count=1,
        )
        for i in range(n)
    ]
    mock_manager.generate_topic_label.return_value = ("Test Topic", "gemini")

    with (
        patch("src.bias.service.ensure_bias_tables"),
        patch("src.bias.service._load_recent_articles", return_value=seeded_articles),
        patch("src.bias.service.get_models", return_value=mock_manager),
        patch("src.bias.service.prepare_embeddings", return_value=n),
        patch("src.bias.service.load_analysis_rows", return_value=(analysis_rows, embeddings)),
        patch("src.bias.service.generate_labels_with_gemini", return_value=["Test Topic"] * 20),
        patch("src.bias.service._persist_run_log") as mock_log,
    ):
        mock_log.return_value.id = 1

        from src.bias.service import _run_bias_analysis_impl
        result = _run_bias_analysis_impl(db=db_session, external_clusters=None, skip_embedding=True)

    assert result["status"] == "ok"
    assert result["topics_processed"] >= 1
    assert result["profiles_updated"] >= 1
    db_session.refresh(seeded_articles[0])
    assert seeded_articles[0].entity_sentiments[0]["target"] == "Entity0"


def test_pipeline_returns_empty_result_with_no_articles(db_session):
    with (
        patch("src.bias.service.ensure_bias_tables"),
        patch("src.bias.service._load_recent_articles", return_value=[]),
        patch("src.bias.service.get_models"),
        patch("src.bias.service._persist_run_log"),
    ):
        from src.bias.service import _run_bias_analysis_impl
        result = _run_bias_analysis_impl(db=db_session, external_clusters=None, skip_embedding=True)

    assert result["status"] == "ok"
    assert result["processed_articles"] == 0
    assert result["topics_processed"] == 0


def test_bsi_scores_in_valid_range(db_session, seeded_articles):
    """After a run, all stored BSI scores must be in [0, 1]."""
    n = len(seeded_articles)
    embeddings = _deterministic_embeddings(n)
    analysis_rows = [{"article": a, "text": a.clean_text or ""} for a in seeded_articles]

    mock_manager = MagicMock()
    mock_manager.embedding_model_name = "all-mpnet-base-v2"
    mock_manager.sentiment_model_name = "models/deberta-v3-newsmtsc"
    mock_manager.analyze_sentiment.return_value = [
        SentimentResult(label="neutral", confidence=0.8, score=0.1) for _ in range(n)
    ]
    mock_manager.generate_topic_label.return_value = ("Economics", "gemini")

    with (
        patch("src.bias.service.ensure_bias_tables"),
        patch("src.bias.service._load_recent_articles", return_value=seeded_articles),
        patch("src.bias.service.get_models", return_value=mock_manager),
        patch("src.bias.service.prepare_embeddings", return_value=n),
        patch("src.bias.service.load_analysis_rows", return_value=(analysis_rows, embeddings)),
        patch("src.bias.service.generate_labels_with_gemini", return_value=["Economics"] * 20),
        patch("src.bias.service._persist_run_log") as mock_log,
    ):
        mock_log.return_value.id = 1

        from src.bias.service import _run_bias_analysis_impl
        _run_bias_analysis_impl(db=db_session, external_clusters=None, skip_embedding=True)

    profiles = db_session.query(models.OutletBiasProfile).all()
    for p in profiles:
        if p.bsi_score is not None:
            assert 0.0 <= p.bsi_score <= 1.0, f"BSI out of range for {p.outlet}: {p.bsi_score}"
        if p.bsi_confidence_low is not None and p.bsi_confidence_high is not None:
            assert p.bsi_confidence_low <= p.bsi_confidence_high
