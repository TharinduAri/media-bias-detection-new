from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


DATA_PATH = Path(__file__).resolve().parent / "data" / "sri_lanka_political_actors.json"
POLITICAL_SIDES = {"government", "opposition"}
ACTOR_TYPE_WEIGHTS = {
    "person": 1.0,
    "party": 0.9,
    "bloc": 0.6,
    "institution": 0.25,
}


@dataclass(frozen=True)
class ActorMatch:
    canonical_name: str
    actor_type: str
    side: str
    confidence: float
    matched_alias: str
    party: str | None = None
    role: str | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "canonical_actor": self.canonical_name,
            "political_actor_type": self.actor_type,
            "political_side": self.side,
            "political_side_confidence": round(float(self.confidence), 6),
            "political_party": self.party,
            "political_role": self.role,
            "matched_actor_alias": self.matched_alias,
        }


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_actor_text(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"\b(hon|mr|mrs|ms|dr|prof|attorney|mp|m\.p)\b\.?", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_actor_phrase(text: str, phrase: str) -> bool:
    normalized_text = f" {normalize_actor_text(text)} "
    normalized_phrase = normalize_actor_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in normalized_text


class PoliticalActorRegistry:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.metadata = payload.get("metadata", {})
        self.actors = [item for item in payload.get("actors", []) if isinstance(item, dict)]
        self._alias_rows: List[tuple[str, str, Dict[str, Any]]] = []

        for actor in self.actors:
            aliases = actor.get("aliases", [])
            if not isinstance(aliases, list):
                aliases = []
            canonical = str(actor.get("canonical_name", "") or "").strip()
            for alias in [canonical, *aliases]:
                alias_text = str(alias or "").strip()
                normalized = normalize_actor_text(alias_text)
                if normalized:
                    self._alias_rows.append((normalized, alias_text, actor))

        self._alias_rows.sort(key=lambda row: len(row[0]), reverse=True)

    def resolve(
        self,
        target: str,
        entity_label: str | None = None,
        article_date: date | datetime | None = None,
    ) -> ActorMatch | None:
        normalized_target = normalize_actor_text(target)
        if not normalized_target:
            return None

        resolved_date: date | None = None
        if isinstance(article_date, datetime):
            resolved_date = article_date.date()
        elif isinstance(article_date, date):
            resolved_date = article_date

        best: ActorMatch | None = None
        for normalized_alias, alias_text, actor in self._alias_rows:
            if normalized_target != normalized_alias:
                continue
            if not self._valid_for_date(actor, resolved_date):
                continue
            side = str(actor.get("side", "") or "").strip().lower()
            if not side:
                continue
            confidence = float(actor.get("confidence", 0.75) or 0.75)
            if entity_label and str(entity_label).upper() == "PERSON" and actor.get("actor_type") != "person":
                confidence *= 0.8
            match = ActorMatch(
                canonical_name=str(actor.get("canonical_name", "") or alias_text),
                actor_type=str(actor.get("actor_type", "") or "actor"),
                side=side,
                confidence=max(0.0, min(1.0, confidence)),
                matched_alias=alias_text,
                party=actor.get("party"),
                role=actor.get("role"),
            )
            if best is None or match.confidence > best.confidence:
                best = match
        return best

    def supplemental_targets(self, texts: Sequence[str], existing_targets: Iterable[str]) -> List[tuple[str, str]]:
        existing = {normalize_actor_text(target) for target in existing_targets}
        joined_text = "\n".join(text for text in texts if text)
        additions: List[tuple[str, str]] = []
        seen = set(existing)

        for normalized_alias, alias_text, actor in self._alias_rows:
            if normalized_alias in seen:
                continue
            actor_type = str(actor.get("actor_type", "") or "")
            confidence = float(actor.get("confidence", 0.0) or 0.0)
            if actor_type == "institution":
                continue
            if actor_type == "person" and len(normalized_alias.split()) < 2:
                continue
            if confidence < 0.7:
                continue
            if contains_actor_phrase(joined_text, alias_text):
                label = "PERSON" if actor_type == "person" else "ORG"
                additions.append((alias_text, label))
                seen.add(normalized_alias)
        return additions

    @staticmethod
    def _valid_for_date(actor: Dict[str, Any], article_date: date | None) -> bool:
        if article_date is None:
            return True
        valid_from = _parse_date(actor.get("valid_from"))
        valid_to = _parse_date(actor.get("valid_to"))
        if valid_from and article_date < valid_from:
            return False
        if valid_to and article_date > valid_to:
            return False
        return True


@lru_cache(maxsize=1)
def get_political_actor_registry() -> PoliticalActorRegistry:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return PoliticalActorRegistry(payload)


def enrich_row_with_actor(
    row: Dict[str, Any],
    article_date: date | datetime | None = None,
) -> Dict[str, Any]:
    target = str(row.get("target", "") or "")
    entity_label = row.get("entity_label")
    match = get_political_actor_registry().resolve(target, entity_label, article_date)
    if match is None:
        return row
    row.update(match.as_dict())
    return row


def compute_political_side_metrics(entity_sentiments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    side_score_sum = {"government": 0.0, "opposition": 0.0}
    side_weight_sum = {"government": 0.0, "opposition": 0.0}
    side_counts = {"government": 0, "opposition": 0}

    for row in entity_sentiments:
        side = str(row.get("political_side", "") or "").lower()
        if side not in POLITICAL_SIDES:
            continue
        score = float(row.get("score", 0.0) or 0.0)
        confidence = max(float(row.get("confidence", 0.0) or 0.0), 0.05)
        mentions = max(int(row.get("mentions", 1) or 1), 1)
        title_boost = 1.25 if row.get("title_mention") else 1.0
        actor_confidence = max(float(row.get("political_side_confidence", 0.0) or 0.0), 0.05)
        actor_type = str(row.get("political_actor_type", "") or "").lower()
        type_weight = ACTOR_TYPE_WEIGHTS.get(actor_type, 0.75)
        weight = confidence * actor_confidence * type_weight * mentions * title_boost

        side_score_sum[side] += score * weight
        side_weight_sum[side] += weight
        side_counts[side] += mentions

    government_sentiment = (
        side_score_sum["government"] / side_weight_sum["government"]
        if side_weight_sum["government"] > 0.0
        else None
    )
    opposition_sentiment = (
        side_score_sum["opposition"] / side_weight_sum["opposition"]
        if side_weight_sum["opposition"] > 0.0
        else None
    )

    # A comparative side-bias value is only meaningful when the article contains
    # evidence about both sides. Treating a missing side as neutral (zero) turns
    # one-sided coverage into a comparison that the article never made.
    side_bias = None
    if government_sentiment is not None and opposition_sentiment is not None:
        side_bias = max(
            -1.0,
            min(1.0, float(government_sentiment - opposition_sentiment)),
        )

    return {
        "political_side_bias": side_bias,
        "government_sentiment": government_sentiment,
        "opposition_sentiment": opposition_sentiment,
        "government_target_count": side_counts["government"],
        "opposition_target_count": side_counts["opposition"],
        "political_actor_count": side_counts["government"] + side_counts["opposition"],
    }
