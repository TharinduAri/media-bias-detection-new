from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Sequence

from .actor_registry import (
    compute_political_side_metrics,
    enrich_row_with_actor,
    get_political_actor_registry,
)
from .entity_extraction import split_article_sentences


TARGET_ENTITY_LABELS = {"PERSON", "ORG", "GPE", "NORP"}
MAX_SENTENCES_PER_ARTICLE = 80
MAX_TARGET_PAIRS_PER_ARTICLE = 96
MAX_AGGREGATE_TARGETS_PER_ARTICLE = 6

ENTITY_SALIENCE_WEIGHTS = {
    "PERSON": 1.0,
    "ORG": 0.85,
    "NORP": 0.55,
    "GPE": 0.35,
}


@dataclass(frozen=True)
class TargetPair:
    article_index: int
    target: str
    entity_label: str
    sentence: str
    sentence_index: int
    is_title: bool = False
    article_date: Any = None
    canonical_target: str | None = None


@dataclass(frozen=True)
class SentimentResult:
    label: str
    confidence: float
    score: float
    entity_sentiments: List[Dict[str, Any]] = field(default_factory=list)
    sentence_sentiments: List[Dict[str, Any]] = field(default_factory=list)
    target_pair_count: int = 0
    political_side_bias: float | None = None
    government_sentiment: float | None = None
    opposition_sentiment: float | None = None
    government_target_count: int = 0
    opposition_target_count: int = 0
    political_actor_count: int = 0


def _article_sentences(article: Any) -> List[tuple[str, bool]]:
    result: List[tuple[str, bool]] = []
    title = str(getattr(article, "title", "") or "").strip()
    if title:
        result.append((title, True))

    body_sentences = split_article_sentences(article, MAX_SENTENCES_PER_ARTICLE)

    seen = {title.casefold()} if title else set()
    for sentence in body_sentences[:MAX_SENTENCES_PER_ARTICLE]:
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((sentence, False))
    return result


def _article_entities(article: Any) -> List[tuple[str, str]]:
    raw_entities = getattr(article, "entities", None)
    if not isinstance(raw_entities, list):
        return []

    result: List[tuple[str, str]] = []
    seen = set()
    for item in raw_entities:
        text = ""
        label = ""
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            for key in ("text", "entity", "name", "value"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    text = candidate
                    break
            raw_label = item.get("label") or item.get("type") or item.get("entity_group")
            if raw_label is not None:
                label = str(raw_label).strip().upper()

        text = re.sub(r"\s+", " ", text).strip(" \t\r\n,.;:()[]{}")
        if (
            len(text) < 2
            or text.isdigit()
            or (label and label not in TARGET_ENTITY_LABELS)
        ):
            continue

        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((text, label))
    return result


def _contains_target(sentence: str, target: str) -> bool:
    pattern = re.compile(
        rf"(?<!\w){re.escape(target)}(?!\w)",
        flags=re.IGNORECASE,
    )
    return pattern.search(sentence) is not None


def build_target_pairs(articles: Sequence[Any]) -> List[TargetPair]:
    pairs: List[TargetPair] = []
    registry = get_political_actor_registry()
    for article_index, article in enumerate(articles):
        article_pairs: List[TargetPair] = []
        sentences = _article_sentences(article)
        entities = _article_entities(article)
        existing_targets = [target for target, _ in entities]
        sentence_texts = [sentence for sentence, _ in sentences]
        entities.extend(registry.supplemental_targets(sentence_texts, existing_targets))
        seen_pair_keys: set[tuple[str, int]] = set()
        for target, entity_label in entities:
            actor_match = registry.resolve(
                target,
                entity_label,
                getattr(article, "date", None),
            )
            canonical_target = actor_match.canonical_name if actor_match else target
            canonical_key = canonical_target.casefold()
            for sentence_index, (sentence, is_title) in enumerate(sentences):
                if not _contains_target(sentence, target):
                    continue
                pair_key = (canonical_key, sentence_index)
                if pair_key in seen_pair_keys:
                    continue
                seen_pair_keys.add(pair_key)
                article_pairs.append(
                    TargetPair(
                        article_index=article_index,
                        target=target,
                        entity_label=entity_label,
                        sentence=sentence,
                        sentence_index=sentence_index,
                        is_title=is_title,
                        article_date=getattr(article, "date", None),
                        canonical_target=canonical_target,
                    )
                )
                if len(article_pairs) >= MAX_TARGET_PAIRS_PER_ARTICLE:
                    break
            if len(article_pairs) >= MAX_TARGET_PAIRS_PER_ARTICLE:
                break
        pairs.extend(article_pairs)
    return pairs


def _label_from_probabilities(probabilities: Dict[str, float]) -> str:
    return max(
        ("negative", "neutral", "positive"),
        key=lambda label: probabilities.get(label, 0.0),
    )


def aggregate_target_sentiment(
    article_count: int,
    pairs: Sequence[TargetPair],
    distributions: Sequence[Dict[str, float]],
) -> List[SentimentResult]:
    if len(pairs) != len(distributions):
        raise ValueError("Target pairs and sentiment distributions must have equal length.")

    grouped: Dict[int, Dict[str, Dict[str, Any]]] = {}
    sentence_rows_by_article: Dict[int, List[Dict[str, Any]]] = {}
    for pair, raw_distribution in zip(pairs, distributions):
        probabilities = {
            label: max(float(raw_distribution.get(label, 0.0)), 0.0)
            for label in ("negative", "neutral", "positive")
        }
        total = sum(probabilities.values())
        if total <= 0.0:
            probabilities = {"negative": 0.0, "neutral": 1.0, "positive": 0.0}
        else:
            probabilities = {
                label: value / total for label, value in probabilities.items()
            }

        pair_label = _label_from_probabilities(probabilities)
        pair_confidence = probabilities[pair_label]
        pair_score = probabilities["positive"] - probabilities["negative"]
        sentence_row = enrich_row_with_actor(
            {
                "target": pair.target,
                "entity_label": pair.entity_label or None,
                "sentence": pair.sentence,
                "sentence_index": int(pair.sentence_index),
                "is_title": bool(pair.is_title),
                "label": pair_label,
                "score": round(float(pair_score), 6),
                "confidence": round(float(pair_confidence), 6),
                "negative": round(float(probabilities["negative"]), 6),
                "neutral": round(float(probabilities["neutral"]), 6),
                "positive": round(float(probabilities["positive"]), 6),
            },
            pair.article_date,
        )
        sentence_rows_by_article.setdefault(pair.article_index, []).append(sentence_row)

        article_targets = grouped.setdefault(pair.article_index, {})
        target_key = (pair.canonical_target or pair.target).casefold()
        target_stats = article_targets.setdefault(
            target_key,
            {
                "target": pair.target,
                "entity_label": pair.entity_label,
                "mentions": 0,
                "title_mention": False,
                "weight": 0.0,
                "probabilities": {
                    "negative": 0.0,
                    "neutral": 0.0,
                    "positive": 0.0,
                },
            },
        )
        actor_match = sentence_row.get("canonical_actor")
        if actor_match and "actor" not in target_stats:
            target_stats["actor"] = {
                key: value
                for key, value in sentence_row.items()
                if key.startswith("political_")
                or key in {"canonical_actor", "political_party", "political_role", "matched_actor_alias"}
            }

        context_weight = 1.5 if pair.is_title else 1.0 / math.sqrt(max(pair.sentence_index, 1))
        target_stats["mentions"] += 1
        target_stats["title_mention"] = target_stats["title_mention"] or pair.is_title
        target_stats["weight"] += context_weight
        for label, value in probabilities.items():
            target_stats["probabilities"][label] += value * context_weight

    results: List[SentimentResult] = []
    for article_index in range(article_count):
        target_rows: List[Dict[str, Any]] = []
        for stats in grouped.get(article_index, {}).values():
            context_weight = float(stats["weight"])
            probabilities = {
                label: float(value) / context_weight
                for label, value in stats["probabilities"].items()
            }
            label = _label_from_probabilities(probabilities)
            confidence = probabilities[label]
            score = probabilities["positive"] - probabilities["negative"]
            entity_weight = ENTITY_SALIENCE_WEIGHTS.get(
                str(stats["entity_label"] or "").upper(),
                0.5,
            )
            actor_weight = 1.35 if isinstance(stats.get("actor"), dict) else 1.0
            importance = (
                (1.0 + math.log1p(int(stats["mentions"])))
                * (1.5 if stats["title_mention"] else 1.0)
                * entity_weight
                * actor_weight
            )

            target_row = {
                    "target": stats["target"],
                    "entity_label": stats["entity_label"] or None,
                    "label": label,
                    "score": round(float(score), 6),
                    "confidence": round(float(confidence), 6),
                    "negative": round(float(probabilities["negative"]), 6),
                    "neutral": round(float(probabilities["neutral"]), 6),
                    "positive": round(float(probabilities["positive"]), 6),
                    "mentions": int(stats["mentions"]),
                    "title_mention": bool(stats["title_mention"]),
                    "salience_weight": round(float(importance), 6),
                }
            if isinstance(stats.get("actor"), dict):
                target_row.update(stats["actor"])
            else:
                enrich_row_with_actor(target_row)
            target_rows.append(target_row)

        if not target_rows:
            political_metrics = compute_political_side_metrics(target_rows)
            results.append(
                SentimentResult(
                    label="neutral",
                    confidence=0.0,
                    score=0.0,
                    sentence_sentiments=sentence_rows_by_article.get(article_index, []),
                    political_side_bias=political_metrics["political_side_bias"],
                    government_sentiment=political_metrics["government_sentiment"],
                    opposition_sentiment=political_metrics["opposition_sentiment"],
                    government_target_count=political_metrics["government_target_count"],
                    opposition_target_count=political_metrics["opposition_target_count"],
                    political_actor_count=political_metrics["political_actor_count"],
                )
            )
            continue

        salient_rows = [
            row
            for row in target_rows
            if row.get("canonical_actor")
            or row["title_mention"]
            or row.get("entity_label") in {"PERSON", "ORG"}
        ]
        if not salient_rows:
            salient_rows = list(target_rows)
        salient_rows.sort(
            key=lambda row: (
                bool(row.get("canonical_actor")),
                row["title_mention"],
                row["mentions"],
                row["salience_weight"],
            ),
            reverse=True,
        )
        aggregate_rows = salient_rows[:MAX_AGGREGATE_TARGETS_PER_ARTICLE]
        article_probability_sums = {
            "negative": 0.0,
            "neutral": 0.0,
            "positive": 0.0,
        }
        article_weight = 0.0
        for row in aggregate_rows:
            aggregate_weight = max(float(row["salience_weight"]), 0.05)
            for probability_label in article_probability_sums:
                article_probability_sums[probability_label] += (
                    float(row[probability_label]) * aggregate_weight
                )
            article_weight += aggregate_weight

        article_probabilities = {
            label: value / article_weight
            for label, value in article_probability_sums.items()
        }
        article_label = _label_from_probabilities(article_probabilities)
        article_score = (
            article_probabilities["positive"] - article_probabilities["negative"]
        )
        target_rows.sort(
            key=lambda row: (row["title_mention"], row["mentions"], row["confidence"]),
            reverse=True,
        )
        political_metrics = compute_political_side_metrics(target_rows)
        results.append(
            SentimentResult(
                label=article_label,
                confidence=round(float(article_probabilities[article_label]), 6),
                score=round(float(max(-1.0, min(1.0, article_score))), 6),
                entity_sentiments=target_rows,
                sentence_sentiments=sentence_rows_by_article.get(article_index, []),
                target_pair_count=sum(row["mentions"] for row in target_rows),
                political_side_bias=political_metrics["political_side_bias"],
                government_sentiment=political_metrics["government_sentiment"],
                opposition_sentiment=political_metrics["opposition_sentiment"],
                government_target_count=political_metrics["government_target_count"],
                opposition_target_count=political_metrics["opposition_target_count"],
                political_actor_count=political_metrics["political_actor_count"],
            )
        )
    return results


def align_sentiment_to_shared_targets(
    articles: Sequence[Any],
    results: Sequence[SentimentResult],
) -> List[SentimentResult]:
    """Re-aggregate each article using targets also discussed by another outlet.

    Relative media-bias comparisons should not compare sentiment toward unrelated
    entities. When a cluster has shared salient targets, this function limits the
    article summary to those targets. Articles without a shared target keep their
    original result rather than inventing evidence.
    """
    if len(articles) != len(results):
        raise ValueError("Articles and sentiment results must have equal length.")

    target_outlets: Dict[str, set[str]] = {}
    rows_by_article: List[List[tuple[str, Dict[str, Any]]]] = []
    for article, result in zip(articles, results):
        outlet = str(getattr(article, "outlet", "") or "")
        article_rows: List[tuple[str, Dict[str, Any]]] = []
        for row in result.entity_sentiments:
            if not (
                row.get("canonical_actor")
                or row.get("title_mention")
                or row.get("entity_label") in {"PERSON", "ORG"}
            ):
                continue
            target = str(row.get("canonical_actor") or row.get("target") or "").strip()
            key = re.sub(r"\s+", " ", target).casefold()
            if not key:
                continue
            article_rows.append((key, row))
            target_outlets.setdefault(key, set()).add(outlet)
        rows_by_article.append(article_rows)

    shared_targets = {
        key for key, outlets in target_outlets.items() if len(outlets) >= 2
    }
    if not shared_targets:
        return list(results)

    aligned: List[SentimentResult] = []
    for result, article_rows in zip(results, rows_by_article):
        comparable_rows = [row for key, row in article_rows if key in shared_targets]
        if not comparable_rows:
            aligned.append(result)
            continue

        probability_sums = {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
        total_weight = 0.0
        for row in comparable_rows:
            weight = max(float(row.get("salience_weight", 1.0) or 1.0), 0.05)
            for label in probability_sums:
                probability_sums[label] += float(row.get(label, 0.0) or 0.0) * weight
            total_weight += weight
        if sum(probability_sums.values()) <= 1e-8:
            aligned.append(result)
            continue
        probabilities = {
            label: value / total_weight for label, value in probability_sums.items()
        }
        label = _label_from_probabilities(probabilities)
        aligned.append(
            replace(
                result,
                label=label,
                confidence=round(float(probabilities[label]), 6),
                score=round(
                    float(probabilities["positive"] - probabilities["negative"]),
                    6,
                ),
            )
        )
    return aligned


def outlet_balanced_peer_references(
    outlets: Sequence[str],
    scores: Sequence[float],
) -> Dict[str, float]:
    """Return leave-one-out references after giving each outlet equal weight."""
    if len(outlets) != len(scores):
        raise ValueError("Outlets and scores must have equal length.")
    scores_by_outlet: Dict[str, List[float]] = {}
    for outlet, score in zip(outlets, scores):
        scores_by_outlet.setdefault(outlet, []).append(float(score))
    outlet_means = {
        outlet: sum(values) / len(values)
        for outlet, values in scores_by_outlet.items()
        if values
    }
    references: Dict[str, float] = {}
    for outlet, own_mean in outlet_means.items():
        peers = [mean for peer, mean in outlet_means.items() if peer != outlet]
        references[outlet] = sum(peers) / len(peers) if peers else own_mean
    return references
