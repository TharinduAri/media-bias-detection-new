from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence


NER_LABEL_MAP = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "ORG": "ORG",
    "LOC": "GPE",
    "LOCATION": "GPE",
    "GPE": "GPE",
    "MISC": "NORP",
    "NORP": "NORP",
}


@dataclass(frozen=True)
class EntityPreparationStats:
    articles_scanned: int
    articles_with_sentences_added: int
    articles_with_entities_added: int
    sentences_scanned: int
    entities_extracted: int


def split_article_sentences(article: Any, limit: int = 80) -> List[str]:
    stored = getattr(article, "sentences", None)
    if isinstance(stored, list):
        cleaned = [
            re.sub(r"\s+", " ", value).strip()
            for value in stored
            if isinstance(value, str) and value.strip()
        ]
        if cleaned:
            return cleaned[:limit]

    source = str(
        getattr(article, "clean_text", "")
        or getattr(article, "text", "")
        or ""
    ).strip()
    if not source:
        return []

    source = re.sub(r"\s+", " ", source)
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])", source)
        if sentence.strip()
    ][:limit]


def normalize_ner_predictions(
    text: str,
    predictions: Iterable[Dict[str, Any]],
    min_score: float,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for prediction in predictions:
        raw_label = (
            prediction.get("entity_group")
            or prediction.get("entity")
            or prediction.get("label")
            or ""
        )
        label = NER_LABEL_MAP.get(str(raw_label).upper())
        score = float(prediction.get("score", 0.0))
        if not label or score < min_score:
            continue

        start = prediction.get("start")
        end = prediction.get("end")
        has_offsets = (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(text)
        )
        entity_text = ""
        if has_offsets:
            entity_text = text[start:end]
        if not entity_text:
            entity_text = str(prediction.get("word") or prediction.get("text") or "")

        entity_text = re.sub(r"\s+", " ", entity_text).strip(" \t\r\n,.;:()[]{}\"'")
        if len(entity_text) < 2 or entity_text.isdigit():
            continue
        candidates.append(
            {
                "text": entity_text,
                "label": label,
                "score": score,
                "start": start if has_offsets else None,
                "end": end if has_offsets else None,
            }
        )

    entities: List[Dict[str, Any]] = []
    for candidate in candidates:
        previous = entities[-1] if entities else None
        start = candidate["start"]
        previous_end = previous.get("end") if previous else None
        can_merge = (
            previous is not None
            and previous["label"] == candidate["label"]
            and isinstance(previous_end, int)
            and isinstance(start, int)
            and previous_end <= start
            and not text[previous_end:start].strip()
        )
        if can_merge:
            previous_start = previous["start"]
            candidate_end = candidate["end"]
            previous_length = max(previous_end - previous_start, 1)
            candidate_length = max(candidate_end - start, 1)
            previous["score"] = (
                (previous["score"] * previous_length)
                + (candidate["score"] * candidate_length)
            ) / (previous_length + candidate_length)
            previous["end"] = candidate_end
            previous["text"] = re.sub(
                r"\s+",
                " ",
                text[previous_start:candidate_end],
            ).strip()
            continue
        entities.append(candidate)

    for entity in entities:
        entity["score"] = round(float(entity["score"]), 6)
        entity.pop("start", None)
        entity.pop("end", None)
    return entities


def merge_article_entities(
    existing: object,
    extracted_groups: Sequence[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("name") or "").strip()
            label = str(item.get("label") or item.get("type") or "").upper()
            if text and label:
                merged[(text.casefold(), label)] = dict(item)

    for group in extracted_groups:
        for item in group:
            text = str(item.get("text") or "").strip()
            label = str(item.get("label") or "").upper()
            if not text or not label:
                continue
            key = (text.casefold(), label)
            previous = merged.get(key)
            if previous is None or float(item.get("score", 0.0)) > float(
                previous.get("score", 0.0)
            ):
                merged[key] = dict(item)
    return list(merged.values())
