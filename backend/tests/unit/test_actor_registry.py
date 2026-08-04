from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bias.actor_registry import (
    compute_political_side_metrics,
    get_political_actor_registry,
)
from src.bias.target_sentiment import aggregate_target_sentiment, build_target_pairs


def test_registry_resolves_current_government_and_opposition_actors():
    registry = get_political_actor_registry()

    government = registry.resolve("Harini Amarasuriya", "PERSON")
    opposition = registry.resolve("Sajith Premadasa", "PERSON")

    assert government is not None
    assert government.side == "government"
    assert government.actor_type == "person"
    assert opposition is not None
    assert opposition.side == "opposition"


def test_build_target_pairs_adds_registry_targets_without_ner_entities():
    article = SimpleNamespace(
        title="Government rejects Opposition criticism of NPP budget",
        sentences=["The Opposition said the NPP budget hurts families."],
        entities=[],
        clean_text="",
        text="",
    )

    pairs = build_target_pairs([article])
    targets = {pair.target for pair in pairs}

    assert "Government" in targets
    assert "Opposition" in targets
    assert "NPP" in targets


def test_aggregate_target_sentiment_computes_political_side_bias():
    article = SimpleNamespace(
        title="Government and Opposition debate the budget",
        sentences=["Government defended the plan.", "Opposition criticised the plan."],
        entities=[],
        clean_text="",
        text="",
    )
    pairs = build_target_pairs([article])
    distributions = []
    for pair in pairs:
        if pair.target == "Government":
            distributions.append({"negative": 0.1, "neutral": 0.1, "positive": 0.8})
        elif pair.target == "Opposition":
            distributions.append({"negative": 0.7, "neutral": 0.2, "positive": 0.1})
        else:
            distributions.append({"negative": 0.0, "neutral": 1.0, "positive": 0.0})

    result = aggregate_target_sentiment(1, pairs, distributions)[0]
    actors = {row["target"]: row for row in result.entity_sentiments}

    assert actors["Government"]["political_side"] == "government"
    assert actors["Opposition"]["political_side"] == "opposition"
    assert result.government_sentiment is not None
    assert result.opposition_sentiment is not None
    assert result.political_side_bias == pytest.approx(1.0, abs=1e-6)


def test_compute_political_side_metrics_handles_one_sided_evidence():
    metrics = compute_political_side_metrics([
        {
            "target": "Government",
            "political_side": "government",
            "political_side_confidence": 0.9,
            "score": -0.4,
            "confidence": 0.8,
            "mentions": 2,
        }
    ])

    assert metrics["political_side_bias"] == pytest.approx(-0.4, abs=1e-6)
    assert metrics["government_target_count"] == 2
    assert metrics["opposition_target_count"] == 0
