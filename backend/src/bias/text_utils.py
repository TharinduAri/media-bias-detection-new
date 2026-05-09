from __future__ import annotations

import os
import re
from typing import List, Set

from api import models

CLUSTER_TEXT_SENTENCE_LIMIT = int(os.getenv("BIAS_CLUSTER_TEXT_SENTENCE_LIMIT", "12"))
CLUSTER_TEXT_CHAR_LIMIT = int(os.getenv("BIAS_CLUSTER_TEXT_CHAR_LIMIT", "3600"))
CLUSTER_TITLE_REPEAT = max(1, int(os.getenv("BIAS_CLUSTER_TITLE_REPEAT", "1")))
CLUSTER_ENTITY_LIMIT = int(os.getenv("BIAS_CLUSTER_ENTITY_LIMIT", "12"))


def _build_outlet_blocklist(outlets: List[str]) -> Set[str]:
    blocklist: Set[str] = set()
    for outlet in outlets:
        cleaned = (outlet or "").strip()
        if cleaned:
            blocklist.add(cleaned)
            blocklist.add(cleaned.replace(" ", ""))
            blocklist.add(cleaned.replace(" ", "-"))
            blocklist.add(cleaned.replace(" ", "_"))
    blocklist.update(
        {
            "daily ft",
            "dailyft",
            "ft",
            "economy next",
            "economynext",
            "lanka business online",
            "lbo",
            "ada derana",
            "adaderana",
            "ceylon today",
            "ceylontoday",
            "newsfirst",
            "daily mirror",
            "dailymirror",
            "the morning",
            "themorning",
            "daily news",
            "dailynews",
            "the island",
            "island",
            "sunday observer",
            "sundayobserver",
            "colombo gazette",
            "colombogazette",
            "colombo page",
            "colombopage",
            "news lk",
            "newslk",
        }
    )
    return {item for item in blocklist if item}


def _strip_outlet_markers(text: str, outlet_blocklist: Set[str]) -> str:
    if not text:
        return ""
    cleaned = text
    for token in sorted(outlet_blocklist, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(token)}\b", flags=re.IGNORECASE)
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _sanitize_topic_label(label: str, outlet_blocklist: Set[str]) -> str:
    cleaned = _strip_outlet_markers(label or "", outlet_blocklist)
    cleaned = re.sub(r"\b(202\d|19\d\d)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(news|headline|update|report)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_,.;:")
    words = [w for w in cleaned.split() if len(w) > 2]
    if len(words) < 2:
        return ""
    return " ".join(words[:6])


def _first_sentences_from_text(text: str, limit: int) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(part.strip() for part in parts[:limit] if part.strip())


def _entity_hint_text(entities_raw: object) -> str:
    if not isinstance(entities_raw, list):
        return ""
    terms: List[str] = []
    seen: Set[str] = set()
    for item in entities_raw:
        value = ""
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            for key in ("text", "entity", "name", "value"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    value = candidate.strip()
                    break
        if not value:
            continue
        normalized = re.sub(r"\s+", " ", value).strip()
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(normalized)
        if len(terms) >= CLUSTER_ENTITY_LIMIT:
            break
    return ", ".join(terms)


def _build_article_text(article: models.Article, outlet_blocklist: Set[str]) -> str:
    title = (article.title or "").strip()
    sentences = article.sentences if isinstance(article.sentences, list) else []
    source_text = (article.clean_text or article.text or "").strip()

    snippet = ""
    if sentences:
        snippet = " ".join(
            [s.strip() for s in sentences[:CLUSTER_TEXT_SENTENCE_LIMIT] if isinstance(s, str) and s.strip()]
        )
    else:
        snippet = _first_sentences_from_text(source_text, CLUSTER_TEXT_SENTENCE_LIMIT)

    entities_hint = _entity_hint_text(article.entities)

    segments: List[str] = []
    if title:
        weighted_title = ". ".join([title] * CLUSTER_TITLE_REPEAT)
        segments.append(weighted_title)
    if entities_hint:
        segments.append(f"Entities: {entities_hint}")
    if snippet:
        segments.append(snippet)
    if source_text and len(snippet) < min(400, CLUSTER_TEXT_CHAR_LIMIT // 4):
        segments.append(source_text[:CLUSTER_TEXT_CHAR_LIMIT])

    combined = " ".join(segment for segment in segments if segment).strip()
    cleaned = _strip_outlet_markers(combined, outlet_blocklist)
    return cleaned[:CLUSTER_TEXT_CHAR_LIMIT].strip()


def _label_to_score(label: str, confidence: float) -> float:
    normalized = label.lower()
    if "positive" in normalized:
        return confidence
    if "negative" in normalized:
        return -confidence
    return 0.0
