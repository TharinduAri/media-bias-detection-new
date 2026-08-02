from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .entity_extraction import split_article_sentences


TARGET_ENTITY_LABELS = {"PERSON", "ORG", "GPE", "NORP"}
MAX_SENTENCES_PER_ARTICLE = 80
MAX_TARGET_PAIRS_PER_ARTICLE = 96


@dataclass(frozen=True)
class TargetPair:
    article_index: int
    target: str
    entity_label: str
    sentence: str
    sentence_index: int
    is_title: bool = False


@dataclass(frozen=True)
class SentimentResult:
    label: str
    confidence: float
    score: float
    entity_sentiments: List[Dict[str, Any]] = field(default_factory=list)
    sentence_sentiments: List[Dict[str, Any]] = field(default_factory=list)
    target_pair_count: int = 0


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
    for article_index, article in enumerate(articles):
        article_pairs: List[TargetPair] = []
        sentences = _article_sentences(article)
        for target, entity_label in _article_entities(article):
            for sentence_index, (sentence, is_title) in enumerate(sentences):
                if not _contains_target(sentence, target):
                    continue
                article_pairs.append(
                    TargetPair(
                        article_index=article_index,
                        target=target,
                        entity_label=entity_label,
                        sentence=sentence,
                        sentence_index=sentence_index,
                        is_title=is_title,
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
        sentence_rows_by_article.setdefault(pair.article_index, []).append(
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
            }
        )

        article_targets = grouped.setdefault(pair.article_index, {})
        target_key = pair.target.casefold()
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

        context_weight = 1.5 if pair.is_title else 1.0 / math.sqrt(max(pair.sentence_index, 1))
        target_stats["mentions"] += 1
        target_stats["title_mention"] = target_stats["title_mention"] or pair.is_title
        target_stats["weight"] += context_weight
        for label, value in probabilities.items():
            target_stats["probabilities"][label] += value * context_weight

    results: List[SentimentResult] = []
    for article_index in range(article_count):
        target_rows: List[Dict[str, Any]] = []
        article_probability_sums = {
            "negative": 0.0,
            "neutral": 0.0,
            "positive": 0.0,
        }
        article_weight = 0.0

        for stats in grouped.get(article_index, {}).values():
            context_weight = float(stats["weight"])
            probabilities = {
                label: float(value) / context_weight
                for label, value in stats["probabilities"].items()
            }
            label = _label_from_probabilities(probabilities)
            confidence = probabilities[label]
            score = probabilities["positive"] - probabilities["negative"]
            importance = (1.0 + math.log1p(int(stats["mentions"]))) * (
                1.25 if stats["title_mention"] else 1.0
            )
            aggregate_weight = max(confidence, 0.05) * importance

            for probability_label, value in probabilities.items():
                article_probability_sums[probability_label] += value * aggregate_weight
            article_weight += aggregate_weight

            target_rows.append(
                {
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
                }
            )

        if not target_rows or article_weight <= 0.0:
            results.append(
                SentimentResult(
                    label="neutral",
                    confidence=0.0,
                    score=0.0,
                    sentence_sentiments=sentence_rows_by_article.get(article_index, []),
                )
            )
            continue

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
        results.append(
            SentimentResult(
                label=article_label,
                confidence=round(float(article_probabilities[article_label]), 6),
                score=round(float(max(-1.0, min(1.0, article_score))), 6),
                entity_sentiments=target_rows,
                sentence_sentiments=sentence_rows_by_article.get(article_index, []),
                target_pair_count=sum(row["mentions"] for row in target_rows),
            )
        )
    return results
