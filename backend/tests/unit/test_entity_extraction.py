from __future__ import annotations

from types import SimpleNamespace

from src.bias.entity_extraction import (
    merge_article_entities,
    normalize_ner_predictions,
    split_article_sentences,
)


def test_split_article_sentences_uses_clean_text_fallback():
    article = SimpleNamespace(
        sentences=None,
        clean_text="First sentence. Second sentence! Third sentence?",
        text="",
    )

    assert split_article_sentences(article) == [
        "First sentence.",
        "Second sentence!",
        "Third sentence?",
    ]


def test_normalize_ner_predictions_maps_labels_and_uses_exact_offsets():
    text = "Anura met Acme in Colombo with Sri Lankan officials."
    predictions = [
        {"entity_group": "PER", "score": 0.99, "start": 0, "end": 5},
        {"entity_group": "ORG", "score": 0.98, "start": 10, "end": 14},
        {"entity_group": "LOC", "score": 0.97, "start": 18, "end": 25},
        {"entity_group": "MISC", "score": 0.96, "start": 31, "end": 42},
        {"entity_group": "ORG", "score": 0.40, "start": 10, "end": 14},
    ]

    assert normalize_ner_predictions(text, predictions, min_score=0.65) == [
        {"text": "Anura", "label": "PERSON", "score": 0.99},
        {"text": "Acme", "label": "ORG", "score": 0.98},
        {"text": "Colombo", "label": "GPE", "score": 0.97},
        {"text": "Sri Lankan", "label": "NORP", "score": 0.96},
    ]


def test_normalize_ner_predictions_merges_adjacent_same_label_spans():
    text = "Anura Kumara Dissanayake spoke."
    predictions = [
        {"entity_group": "PER", "score": 0.99, "start": 0, "end": 2},
        {"entity_group": "PER", "score": 0.97, "start": 2, "end": 24},
    ]

    entities = normalize_ner_predictions(text, predictions, min_score=0.65)

    assert len(entities) == 1
    assert entities[0]["text"] == "Anura Kumara Dissanayake"
    assert entities[0]["label"] == "PERSON"


def test_merge_article_entities_deduplicates_and_keeps_highest_score():
    merged = merge_article_entities(
        [{"text": "Acme", "label": "ORG", "score": 0.70}],
        [
            [
                {"text": "acme", "label": "ORG", "score": 0.95},
                {"text": "Colombo", "label": "GPE", "score": 0.90},
            ],
            [{"text": "Colombo", "label": "GPE", "score": 0.80}],
        ],
    )

    by_key = {(item["text"].casefold(), item["label"]): item for item in merged}
    assert len(by_key) == 2
    assert by_key[("acme", "ORG")]["score"] == 0.95
    assert by_key[("colombo", "GPE")]["score"] == 0.90
