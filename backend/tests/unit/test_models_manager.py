from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.bias.models_manager import (
    SENTIMENT_MODEL,
    BiasModelManager,
    SentimentResult,
)


def _make_mock_manager() -> BiasModelManager:
    """Construct a BiasModelManager without loading any real ML models."""
    with (
        patch("src.bias.models_manager.SentenceTransformer"),
        patch("src.bias.models_manager.AutoTokenizer"),
        patch("src.bias.models_manager.AutoModelForSequenceClassification") as mock_model_cls,
        patch("src.bias.models_manager.pipeline"),
        patch("src.bias.models_manager.KeyBERT"),
    ):
        # Give the mock model a config with id2label
        mock_model = MagicMock()
        mock_model.config.id2label = {0: "negative", 1: "neutral", 2: "positive"}
        mock_model_cls.from_pretrained.return_value = mock_model
        manager = BiasModelManager("all-mpnet-base-v2")

    # Set id2label explicitly so tests can rely on it
    manager.id2label = {0: "negative", 1: "neutral", 2: "positive"}
    return manager


# ── Default model changed from FinBERT (Fix 1) ────────────────────────────────

def test_default_sentiment_model_is_not_finbert():
    assert "finbert" not in SENTIMENT_MODEL.lower()


def test_default_sentiment_model_is_cardiffnlp():
    assert "cardiffnlp" in SENTIMENT_MODEL.lower()


# ── _canonical_sentiment_label ────────────────────────────────────────────────

def test_canonical_label_positive_lowercase():
    manager = _make_mock_manager()
    assert manager._canonical_sentiment_label("positive") == "positive"


def test_canonical_label_positive_mixed_case():
    manager = _make_mock_manager()
    assert manager._canonical_sentiment_label("Positive") == "positive"
    assert manager._canonical_sentiment_label("POSITIVE") == "positive"


def test_canonical_label_negative():
    manager = _make_mock_manager()
    assert manager._canonical_sentiment_label("Negative") == "negative"
    assert manager._canonical_sentiment_label("NEGATIVE") == "negative"


def test_canonical_label_neutral():
    manager = _make_mock_manager()
    assert manager._canonical_sentiment_label("Neutral") == "neutral"


def test_canonical_label_from_label_id_format():
    manager = _make_mock_manager()
    # LABEL_2 → id2label[2] → "positive"
    assert manager._canonical_sentiment_label("LABEL_2") == "positive"
    assert manager._canonical_sentiment_label("LABEL_0") == "negative"
    assert manager._canonical_sentiment_label("label_1") == "neutral"


def test_canonical_label_unknown_unmapped_label_returns_normalised():
    manager = _make_mock_manager()
    # LABEL_99 has no id2label entry → normalized stays "label_99"
    # (not "neutral" — function returns whatever it can normalise)
    result = manager._canonical_sentiment_label("LABEL_99")
    assert result == "label_99"


# ── _distribution_to_score ────────────────────────────────────────────────────

def test_distribution_score_range():
    manager = _make_mock_manager()
    preds = [
        {"label": "positive", "score": 0.8},
        {"label": "negative", "score": 0.1},
        {"label": "neutral", "score": 0.1},
    ]
    score = manager._distribution_to_score(preds)
    assert -1.0 <= score <= 1.0


def test_distribution_score_positive_dominant():
    manager = _make_mock_manager()
    preds = [{"label": "positive", "score": 0.9}, {"label": "negative", "score": 0.05}]
    score = manager._distribution_to_score(preds)
    assert score > 0


def test_distribution_score_negative_dominant():
    manager = _make_mock_manager()
    preds = [{"label": "positive", "score": 0.05}, {"label": "negative", "score": 0.9}]
    score = manager._distribution_to_score(preds)
    assert score < 0


def test_distribution_score_neutral_only():
    manager = _make_mock_manager()
    preds = [{"label": "neutral", "score": 1.0}]
    score = manager._distribution_to_score(preds)
    assert score == pytest.approx(0.0, abs=1e-6)


# ── _tokenize_into_chunks ─────────────────────────────────────────────────────

def test_tokenize_long_text_produces_multiple_chunks():
    manager = _make_mock_manager()
    # Mock tokenizer that returns 300 token IDs for any text
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = list(range(300))
    mock_tokenizer.decode.side_effect = lambda ids, **kw: " ".join(str(i) for i in ids)
    manager.sentiment_pipeline.tokenizer = mock_tokenizer

    chunks = manager._tokenize_into_chunks("any text here")
    # 300 tokens with chunk_size=256, overlap=32 → at least 2 chunks
    assert len(chunks) >= 2


def test_tokenize_short_text_produces_one_chunk():
    manager = _make_mock_manager()
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = list(range(50))
    mock_tokenizer.decode.side_effect = lambda ids, **kw: "decoded"
    manager.sentiment_pipeline.tokenizer = mock_tokenizer

    chunks = manager._tokenize_into_chunks("short")
    assert len(chunks) == 1


# ── generate_topic_label returns (str, str) tuple ────────────────────────────

def test_generate_topic_label_returns_tuple():
    manager = _make_mock_manager()
    manager.kw_model.extract_keywords.return_value = []

    result = manager.generate_topic_label(
        ["Election Results Announced", "Polling Stations Open"],
        outlet_blocklist=set(),
        gemini_label="Sri Lanka Election 2024",
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
    label, source = result
    assert isinstance(label, str)
    assert isinstance(source, str)


def test_generate_topic_label_gemini_source():
    manager = _make_mock_manager()
    label, source = manager.generate_topic_label(
        ["Some title"],
        outlet_blocklist=set(),
        gemini_label="Valid Gemini Label Here",
    )
    assert source == "gemini"
    assert "Valid Gemini Label" in label


def test_generate_topic_label_fallback_source_on_empty():
    manager = _make_mock_manager()
    label, source = manager.generate_topic_label([], outlet_blocklist=set())
    assert source == "fallback"
    assert label == "Unknown Topic"


def test_generate_topic_label_keybert_fallback():
    manager = _make_mock_manager()
    manager.kw_model.extract_keywords.return_value = [("budget crisis", 0.8)]
    label, source = manager.generate_topic_label(
        ["some article title"],
        outlet_blocklist=set(),
        gemini_label=None,
        cluster_embeddings=None,
    )
    # Either keybert or first_title fallback — both are valid
    assert source in ("keybert", "first_title", "centroid_title", "fallback")
    assert isinstance(label, str)
