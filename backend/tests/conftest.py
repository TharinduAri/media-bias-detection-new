from __future__ import annotations

import sys
import os
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend/ is on the path when running from the tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.database import Base
from api import models
from src.bias.models_manager import SentimentResult


@pytest.fixture
def mock_articles():
    """3 outlets × 2 topics × 5 articles = 30 MagicMock Article objects."""
    topic_data = [
        ("Politics", "Election results announced for the general election"),
        ("Economy", "Central bank raises interest rates amid inflation"),
    ]
    outlets = ["Outlet A", "Outlet B", "Outlet C"]
    articles = []
    for outlet in outlets:
        for topic_name, base_title in topic_data:
            for i in range(5):
                article = MagicMock(spec=models.Article)
                article.id = len(articles) + 1
                article.outlet = outlet
                article.title = f"{base_title} — part {i + 1}"
                article.text = f"This article covers {topic_name}. " * 40
                article.clean_text = article.text
                article.sentences = [f"Sentence {j} about {topic_name}." for j in range(10)]
                article.entities = [{"text": f"Entity{j}", "label": "ORG"} for j in range(3)]
                article.url = f"http://{outlet.lower().replace(' ', '')}.com/{topic_name}/{i}"
                article.date = datetime.utcnow()
                article.created_at = datetime.utcnow()
                articles.append(article)
    return articles


@pytest.fixture
def mock_db_session():
    """SQLite in-memory DB with all bias tables created fresh per test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_model_manager():
    """BiasModelManager returning deterministic fixed results without loading real models."""
    manager = MagicMock()
    manager.embedding_model_name = "all-mpnet-base-v2"
    manager.sentiment_model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"

    def fixed_sentiment(texts):
        return [SentimentResult(label="neutral", confidence=0.8, score=0.1)] * len(texts)

    def fixed_embed(texts):
        rng = np.random.default_rng(42)
        vecs = rng.standard_normal((len(texts), 768)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / (norms + 1e-8)

    manager.analyze_sentiment.side_effect = fixed_sentiment
    manager.embed.side_effect = fixed_embed
    manager.generate_topic_label.return_value = ("Test Topic", "gemini")
    manager.kw_model = MagicMock()
    return manager
