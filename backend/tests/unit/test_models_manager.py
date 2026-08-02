from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.bias.models_manager import (
    DEFAULT_SENTIMENT_MODEL,
    SENTIMENT_MODEL,
    BiasModelManager,
)


def _make_mock_manager() -> BiasModelManager:
    with (
        patch("src.bias.models_manager.SentenceTransformer"),
        patch("src.bias.models_manager.AutoTokenizer"),
        patch("src.bias.models_manager.AutoModelForSequenceClassification") as model_cls,
        patch("src.bias.models_manager.AutoModelForTokenClassification"),
        patch("src.bias.models_manager.pipeline") as pipeline_mock,
        patch("src.bias.models_manager.KeyBERT"),
        patch("src.bias.models_manager.SENTIMENT_MODEL", "test-target-model"),
    ):
        model = MagicMock()
        model.config.id2label = {0: "negative", 1: "neutral", 2: "positive"}
        model_cls.from_pretrained.return_value = model
        pipeline_mock.return_value = MagicMock(return_value=[])
        manager = BiasModelManager("all-mpnet-base-v2")

    manager.id2label = {0: "negative", 1: "neutral", 2: "positive"}
    return manager


def test_default_sentiment_model_is_newsmtsc_deberta():
    assert "deberta-v3-newsmtsc" in str(DEFAULT_SENTIMENT_MODEL).lower()


def test_sentiment_model_does_not_use_twitter_checkpoint():
    assert "twitter" not in SENTIMENT_MODEL.lower()


@pytest.mark.parametrize(
    ("raw_label", "expected"),
    [
        ("positive", "positive"),
        ("POSITIVE", "positive"),
        ("Negative", "negative"),
        ("Neutral", "neutral"),
        ("LABEL_2", "positive"),
        ("LABEL_0", "negative"),
        ("label_1", "neutral"),
        ("LABEL_99", "label_99"),
    ],
)
def test_canonical_sentiment_labels(raw_label, expected):
    manager = _make_mock_manager()
    assert manager._canonical_sentiment_label(raw_label) == expected


@pytest.mark.parametrize(
    ("predictions", "expected_sign"),
    [
        (
            [
                {"label": "positive", "score": 0.8},
                {"label": "negative", "score": 0.1},
                {"label": "neutral", "score": 0.1},
            ],
            1,
        ),
        (
            [
                {"label": "positive", "score": 0.05},
                {"label": "negative", "score": 0.9},
            ],
            -1,
        ),
        ([{"label": "neutral", "score": 1.0}], 0),
    ],
)
def test_distribution_to_score(predictions, expected_sign):
    manager = _make_mock_manager()
    score = manager._distribution_to_score(predictions)
    assert -1.0 <= score <= 1.0
    if expected_sign == 0:
        assert score == pytest.approx(0.0)
    else:
        assert score * expected_sign > 0


def test_generate_topic_label_uses_gemini_label():
    manager = _make_mock_manager()
    label, source = manager.generate_topic_label(
        ["Election Results Announced", "Polling Stations Open"],
        outlet_blocklist=set(),
        gemini_label="Sri Lanka Election 2024",
    )
    assert source == "gemini"
    assert "Sri Lanka Election" in label


def test_generate_topic_label_empty_fallback():
    manager = _make_mock_manager()
    assert manager.generate_topic_label([], outlet_blocklist=set()) == (
        "Unknown Topic",
        "fallback",
    )


def test_generate_topic_label_keybert_fallback():
    manager = _make_mock_manager()
    manager.kw_model.extract_keywords.return_value = [("budget crisis", 0.8)]
    label, source = manager.generate_topic_label(
        ["some article title"],
        outlet_blocklist=set(),
    )
    assert source in ("keybert", "first_title", "centroid_title", "fallback")
    assert isinstance(label, str)


def test_prepare_article_targets_extracts_missing_entities_and_sentences():
    manager = _make_mock_manager()
    article = MagicMock()
    article.title = "President Silva met Acme officials."
    article.clean_text = "President Silva praised Acme. Markets responded."
    article.text = ""
    article.sentences = None
    article.entities = None
    manager.ner_pipeline.return_value = [
        [
            {
                "entity_group": "PER",
                "score": 0.99,
                "start": 10,
                "end": 15,
            },
            {
                "entity_group": "ORG",
                "score": 0.98,
                "start": 20,
                "end": 24,
            },
        ],
        [
            {
                "entity_group": "PER",
                "score": 0.97,
                "start": 10,
                "end": 15,
            },
            {
                "entity_group": "ORG",
                "score": 0.96,
                "start": 24,
                "end": 28,
            },
        ],
        [],
    ]

    stats = manager.prepare_article_targets([article])

    assert article.sentences == [
        "President Silva praised Acme.",
        "Markets responded.",
    ]
    assert {(item["text"], item["label"]) for item in article.entities} == {
        ("Silva", "PERSON"),
        ("Acme", "ORG"),
    }
    assert stats.articles_with_sentences_added == 1
    assert stats.articles_with_entities_added == 1
    assert stats.sentences_scanned == 3
    assert stats.entities_extracted == 2


def test_prepare_article_targets_reuses_existing_entities():
    manager = _make_mock_manager()
    article = MagicMock()
    article.title = "Acme reports earnings"
    article.clean_text = "Acme reported higher earnings."
    article.text = ""
    article.sentences = ["Acme reported higher earnings."]
    article.entities = [{"text": "Acme", "label": "ORG"}]

    stats = manager.prepare_article_targets([article])

    manager.ner_pipeline.assert_not_called()
    assert stats.sentences_scanned == 0
    assert stats.articles_with_entities_added == 0
