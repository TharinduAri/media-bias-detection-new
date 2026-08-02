from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bias.target_sentiment import (
    TargetPair,
    aggregate_target_sentiment,
    build_target_pairs,
)


def _article(title="", sentences=None, entities=None):
    return SimpleNamespace(
        title=title,
        sentences=sentences or [],
        entities=entities or [],
        clean_text="",
        text="",
    )


def test_build_target_pairs_matches_entities_to_title_and_sentences():
    article = _article(
        title="Acme rejects the proposal",
        sentences=[
            "Acme said the proposal would hurt consumers.",
            "The ministry defended it.",
        ],
        entities=[
            {"text": "Acme", "label": "ORG"},
            {"text": "ministry", "label": "ORG"},
        ],
    )
    pairs = build_target_pairs([article])
    assert [(pair.target, pair.is_title) for pair in pairs] == [
        ("Acme", True),
        ("Acme", False),
        ("ministry", False),
    ]


def test_build_target_pairs_uses_phrase_boundaries_and_entity_types():
    article = _article(
        sentences=["The US delegation met Russian officials in Brussels."],
        entities=[
            {"text": "US", "label": "GPE"},
            {"text": "Russian", "label": "NORP"},
            {"text": "Bruss", "label": "PERSON"},
            {"text": "officials", "label": "DATE"},
        ],
    )
    pairs = build_target_pairs([article])
    assert [pair.target for pair in pairs] == ["US", "Russian"]


def test_aggregate_target_sentiment_keeps_targets_separate():
    pairs = [
        TargetPair(0, "Alice", "PERSON", "Alice praised Bob.", 1),
        TargetPair(0, "Bob", "PERSON", "Alice praised Bob.", 1),
    ]
    distributions = [
        {"negative": 0.05, "neutral": 0.15, "positive": 0.80},
        {"negative": 0.70, "neutral": 0.20, "positive": 0.10},
    ]
    result = aggregate_target_sentiment(1, pairs, distributions)[0]
    entities = {row["target"]: row for row in result.entity_sentiments}
    assert entities["Alice"]["label"] == "positive"
    assert entities["Alice"]["score"] == pytest.approx(0.75)
    assert entities["Bob"]["label"] == "negative"
    assert entities["Bob"]["score"] == pytest.approx(-0.60)
    evidence = {(row["target"], row["sentence"]) for row in result.sentence_sentiments}
    assert evidence == {
        ("Alice", "Alice praised Bob."),
        ("Bob", "Alice praised Bob."),
    }
    alice_evidence = next(row for row in result.sentence_sentiments if row["target"] == "Alice")
    assert alice_evidence["positive"] == pytest.approx(0.8)
    assert alice_evidence["score"] == pytest.approx(0.75)
    assert result.target_pair_count == 2


def test_aggregate_target_sentiment_returns_no_evidence_for_unmatched_article():
    result = aggregate_target_sentiment(1, [], [])[0]
    assert result.label == "neutral"
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.entity_sentiments == []
    assert result.sentence_sentiments == []
    assert result.target_pair_count == 0
