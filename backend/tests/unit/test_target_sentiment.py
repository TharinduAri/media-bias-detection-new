from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bias.target_sentiment import (
    SentimentResult,
    TargetPair,
    aggregate_target_sentiment,
    align_sentiment_to_shared_targets,
    build_target_pairs,
    outlet_balanced_peer_references,
)


def _article(title="", sentences=None, entities=None, outlet="Outlet A"):
    return SimpleNamespace(
        title=title,
        sentences=sentences or [],
        entities=entities or [],
        clean_text="",
        text="",
        outlet=outlet,
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


def test_salient_person_target_is_not_drowned_by_background_locations():
    pairs = [
        TargetPair(0, "Leader", "PERSON", "Leader praised the reform.", 0, True),
    ]
    distributions = [{"negative": 0.02, "neutral": 0.03, "positive": 0.95}]
    for index in range(8):
        pairs.append(
            TargetPair(0, f"Region {index}", "GPE", f"Region {index} was listed.", index + 1)
        )
        distributions.append({"negative": 0.01, "neutral": 0.98, "positive": 0.01})

    result = aggregate_target_sentiment(1, pairs, distributions)[0]

    assert result.label == "positive"
    assert result.score > 0.8


def test_shared_target_alignment_excludes_private_background_targets():
    articles = [_article(outlet="A"), _article(outlet="B")]
    results = [
        SentimentResult(
            label="neutral",
            confidence=0.8,
            score=0.0,
            entity_sentiments=[
                {"target": "Shared Org", "entity_label": "ORG", "salience_weight": 2.0,
                 "negative": 0.05, "neutral": 0.05, "positive": 0.9},
                {"target": "Private A", "entity_label": "ORG", "salience_weight": 5.0,
                 "negative": 0.0, "neutral": 1.0, "positive": 0.0},
            ],
        ),
        SentimentResult(
            label="neutral",
            confidence=0.8,
            score=0.0,
            entity_sentiments=[
                {"target": "Shared Org", "entity_label": "ORG", "salience_weight": 2.0,
                 "negative": 0.9, "neutral": 0.05, "positive": 0.05},
                {"target": "Private B", "entity_label": "ORG", "salience_weight": 5.0,
                 "negative": 0.0, "neutral": 1.0, "positive": 0.0},
            ],
        ),
    ]

    aligned = align_sentiment_to_shared_targets(articles, results)

    assert aligned[0].label == "positive"
    assert aligned[0].score == pytest.approx(0.85)
    assert aligned[1].label == "negative"
    assert aligned[1].score == pytest.approx(-0.85)


def test_peer_reference_gives_each_outlet_equal_weight():
    references = outlet_balanced_peer_references(
        ["A", "A", "A", "B", "C"],
        [1.0, 1.0, 1.0, -1.0, 0.0],
    )

    assert references["A"] == pytest.approx(-0.5)
    assert references["B"] == pytest.approx(0.5)
    assert references["C"] == pytest.approx(0.0)
