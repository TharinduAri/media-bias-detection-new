"""
Bias scoring functions: BSI computation, emphasis bias, and DB persistence.

Constant Reference:
  COVERAGE_MAJORITY_THRESHOLD = 0.6
    Fraction of all outlets covering a topic for the binary coverage_majority flag.
    Range: [0.40, 0.80]. Replaced by soft scoring via compute_soft_coverage_score().

  OMISSION_THRESHOLD = 0.15
    coverage_bias_rate delta above historical mean that triggers systematic_omission=True.
    Range: [0.05, 0.30]. Lower = more sensitive omission detection.

  OMISSION_LOOKBACK_RUNS = 5
    Prior runs used as baseline for omission detection.
    Range: [3, 10]. Fewer = faster adaptation; more = stabler baseline.

  compute_bsi weights: sentiment=0.4, coverage=0.4, emphasis=0.2.
    Sentiment normalisation divisor: 0.5 (typical score range for news text).
    Rationale: omission is as important as tonal bias.

  compute_bsi_confidence_interval defaults: n_resamples=1000, ci_level=0.95.
    Range: n_resamples [500, 5000]; ci_level [0.80, 0.99].
"""
from __future__ import annotations

import re
from datetime import datetime
import math
from typing import Any, Dict, Iterable, List, Set, Tuple

import numpy as np
from sqlalchemy.orm import Session

from api import models

COVERAGE_MAJORITY_THRESHOLD = 0.6
OMISSION_THRESHOLD = 0.15
OMISSION_LOOKBACK_RUNS = 5


def compute_bsi(
    sentiment_bias_avg: float,
    coverage_bias_rate: float,
    emphasis_bias_avg: float,
    coverage_bias_rate_soft: float | None = None,
    political_side_bias_avg: float | None = None,
) -> float:
    """Bias Signal Index [0-1]. Higher = more biased.

    BSI = 0.4 * clamp(|sentiment| / 0.5) + 0.4 * coverage_rate + 0.2 * clamp(|emphasis|)

    If coverage_bias_rate_soft is provided it replaces the binary coverage_bias_rate.
    If political_side_bias_avg is provided, political-side skew joins the composite.
    """
    s = min(abs(sentiment_bias_avg) / 0.5, 1.0)
    c_raw = coverage_bias_rate_soft if coverage_bias_rate_soft is not None else coverage_bias_rate
    c = min(max(c_raw, 0.0), 1.0)
    e = min(abs(emphasis_bias_avg), 1.0)
    if political_side_bias_avg is None:
        return round(0.4 * s + 0.4 * c + 0.2 * e, 6)
    p = min(abs(political_side_bias_avg) / 0.5, 1.0)
    return round(0.35 * s + 0.30 * c + 0.20 * e + 0.15 * p, 6)


def compute_source_trust_score(
    bsi_score: float | None,
    sentiment_confidence_avg: float,
    articles_scored: int,
    coverage_bias_rate: float,
    coverage_bias_rate_soft: float | None = None,
) -> float:
    """Source trust score [0-1]. Higher = more trustworthy.

    This is a source-level reliability heuristic, not a factuality verdict. It
    rewards low measured bias, enough scored evidence, and broad topic
    coverage. Sentiment confidence is accepted for API compatibility but is
    deliberately excluded: classifier certainty is not evidence of factuality.
    """
    bsi = min(max(float(bsi_score or 0.0), 0.0), 1.0)
    _ = sentiment_confidence_avg
    coverage_raw = coverage_bias_rate_soft if coverage_bias_rate_soft is not None else coverage_bias_rate
    coverage_quality = 1.0 - min(max(float(coverage_raw), 0.0), 1.0)
    evidence_quality = math.sqrt(min(max(float(articles_scored), 0.0) / 20.0, 1.0))

    score = (
        0.55 * (1.0 - bsi)
        + 0.25 * coverage_quality
        + 0.20 * evidence_quality
    )
    return round(float(min(max(score, 0.0), 1.0)), 6)


def compute_misinformation_risk_score(source_trust_score: float | None) -> float:
    """Inverse of source trust [0-1]. Higher = more misinformation risk."""
    trust = min(max(float(source_trust_score or 0.0), 0.0), 1.0)
    return round(1.0 - trust, 6)


def compute_bsi_confidence_interval(
    sentiment_bias_scores: List[float],
    coverage_bias_rate: float,
    emphasis_bias_scores: List[float],
    n_resamples: int = 1000,
    ci_level: float = 0.95,
    rng_seed: int = 42,
) -> Tuple[float, float]:
    """Bootstrap CI on BSI. Returns (ci_low, ci_high).

    Sentiment and emphasis are resampled jointly (same indices).
    coverage_bias_rate is fixed — it is a ratio, not a sample mean.
    Returns equal values when fewer than 2 articles are present.
    """
    n = len(sentiment_bias_scores)
    if n < 2:
        point = compute_bsi(
            float(np.mean(sentiment_bias_scores)) if sentiment_bias_scores else 0.0,
            coverage_bias_rate,
            float(np.mean(emphasis_bias_scores)) if emphasis_bias_scores else 0.0,
        )
        return (point, point)

    rng = np.random.default_rng(rng_seed)
    sent_arr = np.array(sentiment_bias_scores)
    emph_arr = np.array(emphasis_bias_scores) if len(emphasis_bias_scores) == n else np.zeros(n)

    bsi_samples: List[float] = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        bsi_samples.append(
            compute_bsi(float(np.mean(sent_arr[idx])), coverage_bias_rate, float(np.mean(emph_arr[idx])))
        )

    alpha = 1.0 - ci_level
    low = round(float(np.percentile(bsi_samples, 100 * alpha / 2)), 6)
    high = round(float(np.percentile(bsi_samples, 100 * (1 - alpha / 2))), 6)
    return (low, high)


def compute_soft_coverage_score(
    outlet: str,
    all_outlets: List[str],
    cluster_outlet_sets: List[Set[str]],
    topic_mainstream_weights: List[float],
) -> float:
    """Continuous coverage bias in [0, 1] — replaces the binary COVERAGE_MAJORITY_THRESHOLD cliff.

    missed_penalty = sum of mainstream weights for topics the outlet did not cover.
    covered_weight = outlet's coverage ratio / max outlet coverage ratio across all outlets.
    score = missed_penalty / (covered_weight + missed_penalty).

    A score of 0 means the outlet covered everything relative to peers.
    A score near 1 means the outlet systematically skipped mainstream topics.
    """
    if not cluster_outlet_sets:
        return 0.0

    n_covered = sum(1 for cs in cluster_outlet_sets if outlet in cs)
    outlet_coverage_ratio = n_covered / len(cluster_outlet_sets)

    max_ratio = max(
        (sum(1 for cs in cluster_outlet_sets if o in cs) / len(cluster_outlet_sets) for o in all_outlets),
        default=1.0,
    )
    covered_weight = outlet_coverage_ratio / max(max_ratio, 1e-8)

    missed_penalty = sum(
        w for cs, w in zip(cluster_outlet_sets, topic_mainstream_weights) if outlet not in cs
    )

    total = covered_weight + missed_penalty
    return float(min(1.0, missed_penalty / total)) if total > 1e-8 else 0.0


def init_outlet_stats(outlets: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    return {
        outlet: {
            "sentiment_bias_sum": 0.0,
            "sentiment_score_sum": 0.0,
            "sentiment_confidence_sum": 0.0,
            "emphasis_bias_sum": 0.0,
            "political_side_bias_sum": 0.0,
            "political_side_bias_count": 0.0,
            "government_sentiment_sum": 0.0,
            "government_sentiment_count": 0.0,
            "opposition_sentiment_sum": 0.0,
            "opposition_sentiment_count": 0.0,
            "political_actor_count": 0.0,
            "articles_scored": 0.0,
            "topics_covered": 0.0,
            "topics_considered": 0.0,
            "coverage_missing_majority": 0.0,
            "missed_topics": [],
        }
        for outlet in outlets
    }


def compute_emphasis_bias(
    indices: List[int],
    articles: List[models.Article],
) -> Dict[int, Dict[str, float]]:
    """Multi-component emphasis bias vs. cluster mean, each clamped to [-1, 1].

    Components and weights:
      length_bias   (0.5): relative char count vs. cluster mean
      sentence_bias (0.3): relative sentence count vs. cluster mean
      entity_bias   (0.2): relative named-entity count vs. cluster mean

    Combined: emphasis_bias = 0.5*length + 0.3*sentence + 0.2*entity, clamped [-1, 1].
    Positive = outlet wrote more/denser about this story than peers.
    """

    def _relative(values: Dict[int, float]) -> Dict[int, float]:
        if not values:
            return {idx: 0.0 for idx in indices}
        mean_val = float(np.mean(list(values.values())))
        if mean_val < 1.0:
            return {idx: 0.0 for idx in indices}
        return {
            i: float(max(-1.0, min(1.0, (v - mean_val) / mean_val)))
            for i, v in values.items()
        }

    lengths: Dict[int, float] = {}
    sentence_counts: Dict[int, float] = {}
    entity_counts: Dict[int, float] = {}

    for idx in indices:
        article = articles[idx]
        text = getattr(article, "clean_text", None) or getattr(article, "text", None) or ""
        lengths[idx] = float(len(text))

        sents = getattr(article, "sentences", None)
        if isinstance(sents, list):
            sentence_counts[idx] = float(len(sents))
        else:
            sentence_counts[idx] = float(len(re.split(r"(?<=[.!?])\s+", text))) if text else 0.0

        ents = getattr(article, "entities", None)
        entity_counts[idx] = float(len(ents)) if isinstance(ents, list) else 0.0

    lb = _relative(lengths)
    sb = _relative(sentence_counts)
    eb = _relative(entity_counts)

    result: Dict[int, Dict[str, float]] = {}
    for idx in indices:
        l = lb.get(idx, 0.0)
        s = sb.get(idx, 0.0)
        e = eb.get(idx, 0.0)
        combined = float(max(-1.0, min(1.0, 0.5 * l + 0.3 * s + 0.2 * e)))
        result[idx] = {
            "emphasis_bias": combined,
            "length_bias": l,
            "sentence_bias": s,
            "entity_bias": e,
        }
    return result


def build_profiles(
    outlet_stats: Dict[str, Dict[str, Any]],
    outlet_topic_stats: Dict[str, Dict[str, Dict[str, Any]]],
    now: datetime,
    run_id: int,
    outlet_score_arrays: Dict[str, Dict[str, List[float]]] | None = None,
    outlet_soft_coverage: Dict[str, float] | None = None,
) -> Tuple[List[models.OutletBiasProfile], List[models.OutletTopicBSI]]:
    profiles: List[models.OutletBiasProfile] = []
    topic_bsi_rows: List[models.OutletTopicBSI] = []

    for outlet, stats in outlet_stats.items():
        articles_scored = int(stats["articles_scored"])
        topics_considered = int(stats["topics_considered"])
        sentiment_bias_avg = stats["sentiment_bias_sum"] / articles_scored if articles_scored else 0.0
        sentiment_score_avg = stats["sentiment_score_sum"] / articles_scored if articles_scored else 0.0
        sentiment_confidence_avg = (
            stats["sentiment_confidence_sum"] / articles_scored if articles_scored else 0.0
        )
        emphasis_bias_avg = stats["emphasis_bias_sum"] / articles_scored if articles_scored else 0.0
        political_side_bias_count = int(stats.get("political_side_bias_count", 0))
        political_side_bias_avg = (
            stats.get("political_side_bias_sum", 0.0) / political_side_bias_count
            if political_side_bias_count
            else None
        )
        government_sentiment_count = int(stats.get("government_sentiment_count", 0))
        government_sentiment_avg = (
            stats.get("government_sentiment_sum", 0.0) / government_sentiment_count
            if government_sentiment_count
            else None
        )
        opposition_sentiment_count = int(stats.get("opposition_sentiment_count", 0))
        opposition_sentiment_avg = (
            stats.get("opposition_sentiment_sum", 0.0) / opposition_sentiment_count
            if opposition_sentiment_count
            else None
        )
        political_actor_count = int(stats.get("political_actor_count", 0))
        coverage_missing = int(stats["coverage_missing_majority"])
        coverage_bias_rate = coverage_missing / topics_considered if topics_considered else 0.0
        coverage_soft = outlet_soft_coverage.get(outlet) if outlet_soft_coverage else None
        bsi = compute_bsi(
            sentiment_bias_avg,
            coverage_bias_rate,
            emphasis_bias_avg,
            coverage_soft,
            political_side_bias_avg,
        )
        source_trust = compute_source_trust_score(
            bsi,
            sentiment_confidence_avg,
            articles_scored,
            coverage_bias_rate,
            coverage_soft,
        )
        misinformation_risk = compute_misinformation_risk_score(source_trust)

        arrays = (outlet_score_arrays or {}).get(outlet, {})
        sent_list = arrays.get("sentiment_bias", [])
        emph_list = arrays.get("emphasis_bias", [])
        ci_low, ci_high = compute_bsi_confidence_interval(sent_list, coverage_bias_rate, emph_list)

        topic_article_counts = [
            t["article_count"] for t in outlet_topic_stats.get(outlet, {}).values()
            if t.get("article_count", 0) > 0
        ]
        art_per_topic_avg = (
            float(np.mean(topic_article_counts)) if topic_article_counts else 0.0
        )

        profiles.append(
            models.OutletBiasProfile(
                outlet=outlet,
                sentiment_bias_avg=float(sentiment_bias_avg),
                sentiment_score_avg=float(sentiment_score_avg),
                emphasis_bias_avg=float(emphasis_bias_avg),
                political_side_bias_avg=(
                    float(political_side_bias_avg) if political_side_bias_avg is not None else None
                ),
                government_sentiment_avg=(
                    float(government_sentiment_avg) if government_sentiment_avg is not None else None
                ),
                opposition_sentiment_avg=(
                    float(opposition_sentiment_avg) if opposition_sentiment_avg is not None else None
                ),
                political_actor_count=political_actor_count,
                articles_scored=articles_scored,
                topics_covered=int(stats["topics_covered"]),
                topics_considered=topics_considered,
                coverage_missing_majority=coverage_missing,
                coverage_bias_rate=float(coverage_bias_rate),
                coverage_bias_rate_soft=float(coverage_soft) if coverage_soft is not None else None,
                missed_topics=stats["missed_topics"],
                bsi_score=float(bsi),
                source_trust_score=float(source_trust),
                misinformation_risk_score=float(misinformation_risk),
                bsi_confidence_low=ci_low,
                bsi_confidence_high=ci_high,
                article_count_per_topic_avg=float(art_per_topic_avg),
                updated_at=now,
            )
        )

        for t_key, t in outlet_topic_stats.get(outlet, {}).items():
            cnt = t["article_count"]
            t_sent = t["sentiment_bias_sum"] / cnt if cnt else 0.0
            t_emph = t["emphasis_bias_sum"] / cnt if cnt else 0.0
            t_pol_count = int(t.get("political_side_bias_count", 0))
            t_pol = (
                t.get("political_side_bias_sum", 0.0) / t_pol_count
                if t_pol_count
                else None
            )
            t_cov_rate = 0.0 if t["coverage_present"] else 1.0
            topic_bsi_rows.append(
                models.OutletTopicBSI(
                    run_id=run_id,
                    outlet=outlet,
                    topic_key=t_key,
                    topic_label=t.get("topic_label"),
                    label_source=t.get("label_source"),
                    sentiment_bias_avg=float(t_sent),
                    emphasis_bias_avg=float(t_emph),
                    political_side_bias_avg=float(t_pol) if t_pol is not None else None,
                    coverage_present=bool(t["coverage_present"]),
                    article_count=cnt,
                    bsi_score=compute_bsi(t_sent, t_cov_rate, t_emph, political_side_bias_avg=t_pol),
                    snapshot_date=now,
                )
            )

    return profiles, topic_bsi_rows


def upsert_profiles(db: Session, profiles: Iterable[models.OutletBiasProfile]) -> int:
    updated = 0
    for profile in profiles:
        existing = (
            db.query(models.OutletBiasProfile)
            .filter(models.OutletBiasProfile.outlet == profile.outlet)
            .first()
        )
        if existing:
            existing.sentiment_bias_avg = profile.sentiment_bias_avg
            existing.sentiment_score_avg = profile.sentiment_score_avg
            existing.articles_scored = profile.articles_scored
            existing.topics_covered = profile.topics_covered
            existing.topics_considered = profile.topics_considered
            existing.coverage_missing_majority = profile.coverage_missing_majority
            existing.coverage_bias_rate = profile.coverage_bias_rate
            existing.coverage_bias_rate_soft = profile.coverage_bias_rate_soft
            existing.missed_topics = profile.missed_topics
            existing.emphasis_bias_avg = profile.emphasis_bias_avg
            existing.political_side_bias_avg = profile.political_side_bias_avg
            existing.government_sentiment_avg = profile.government_sentiment_avg
            existing.opposition_sentiment_avg = profile.opposition_sentiment_avg
            existing.political_actor_count = profile.political_actor_count
            existing.bsi_score = profile.bsi_score
            existing.source_trust_score = profile.source_trust_score
            existing.misinformation_risk_score = profile.misinformation_risk_score
            existing.bsi_confidence_low = profile.bsi_confidence_low
            existing.bsi_confidence_high = profile.bsi_confidence_high
            existing.article_count_per_topic_avg = profile.article_count_per_topic_avg
            existing.updated_at = profile.updated_at
        else:
            db.add(profile)
        updated += 1
    db.commit()
    return updated


def upsert_article_bias_scores(db: Session, scores: List[models.ArticleBiasScore]) -> int:
    """Upsert scores keyed on (article_id, topic_key) — one row per article-topic pair."""
    deduped: Dict[Tuple[int, str], models.ArticleBiasScore] = {}
    for score in scores:
        key = (score.article_id, score.topic_key)
        if key not in deduped:
            deduped[key] = score

    if not deduped:
        return 0

    article_ids = {k[0] for k in deduped}
    existing_scores = (
        db.query(models.ArticleBiasScore)
        .filter(models.ArticleBiasScore.article_id.in_(article_ids))
        .all()
    )
    existing_by_key: Dict[Tuple[int, str], models.ArticleBiasScore] = {
        (s.article_id, s.topic_key): s for s in existing_scores
    }

    for (article_id, topic_key), score in deduped.items():
        existing = existing_by_key.get((article_id, topic_key))
        if existing:
            existing.outlet = score.outlet
            existing.topic_label = score.topic_label
            existing.sentiment_label = score.sentiment_label
            existing.sentiment_score = score.sentiment_score
            existing.sentiment_confidence = score.sentiment_confidence
            existing.sentiment_bias = score.sentiment_bias
            existing.group_sentiment_mean = score.group_sentiment_mean
            existing.coverage_majority = score.coverage_majority
            existing.coverage_present = score.coverage_present
            existing.emphasis_bias = score.emphasis_bias
            existing.dominant_outlet = score.dominant_outlet
            existing.emphasis_length_bias = score.emphasis_length_bias
            existing.emphasis_sentence_bias = score.emphasis_sentence_bias
            existing.emphasis_entity_bias = score.emphasis_entity_bias
            existing.political_side_bias = score.political_side_bias
            existing.government_sentiment = score.government_sentiment
            existing.opposition_sentiment = score.opposition_sentiment
            existing.government_target_count = int(score.government_target_count or 0)
            existing.opposition_target_count = int(score.opposition_target_count or 0)
            existing.political_actor_count = int(score.political_actor_count or 0)
            existing.created_at = score.created_at
        else:
            db.add(score)

    db.commit()
    return len(deduped)


def replace_article_bias_evidence(
    db: Session,
    rows: List[models.ArticleBiasEvidence],
    scored_keys: Iterable[Tuple[int, str]] | None = None,
) -> int:
    """Replace sentence-level evidence keyed by (article_id, topic_key)."""
    keys = set(scored_keys or [])
    keys.update((row.article_id, row.topic_key) for row in rows)
    for article_id, topic_key in keys:
        (
            db.query(models.ArticleBiasEvidence)
            .filter(models.ArticleBiasEvidence.article_id == article_id)
            .filter(models.ArticleBiasEvidence.topic_key == topic_key)
            .delete(synchronize_session="fetch")
        )

    if rows:
        db.add_all(rows)
    db.commit()
    return len(rows)


def insert_topic_bsi_rows(db: Session, rows: List[models.OutletTopicBSI]) -> int:
    if not rows:
        return 0
    for row in rows:
        existing = (
            db.query(models.OutletTopicBSI)
            .filter(
                models.OutletTopicBSI.run_id == row.run_id,
                models.OutletTopicBSI.outlet == row.outlet,
                models.OutletTopicBSI.topic_key == row.topic_key,
            )
            .first()
        )
        if existing:
            existing.sentiment_bias_avg = row.sentiment_bias_avg
            existing.emphasis_bias_avg = row.emphasis_bias_avg
            existing.political_side_bias_avg = row.political_side_bias_avg
            existing.coverage_present = row.coverage_present
            existing.article_count = row.article_count
            existing.bsi_score = row.bsi_score
            existing.topic_label = row.topic_label
            existing.label_source = row.label_source
        else:
            db.add(row)
    return len(rows)


def insert_snapshots_with_omission(
    db: Session,
    profiles: List[models.OutletBiasProfile],
    run_id: int,
    now: datetime,
    cross_outlet_coverage_mean: float = 0.0,
) -> None:
    for profile in profiles:
        recent_snaps = (
            db.query(models.OutletBiasSnapshot)
            .filter(models.OutletBiasSnapshot.outlet == profile.outlet)
            .filter(models.OutletBiasSnapshot.run_id != run_id)
            .order_by(models.OutletBiasSnapshot.snapshot_date.desc())
            .limit(OMISSION_LOOKBACK_RUNS)
            .all()
        )

        if recent_snaps:
            baseline_used_runs = len(recent_snaps)
            hist_cov_avg = sum(s.coverage_bias_rate for s in recent_snaps) / baseline_used_runs
            omission_score = round(float(profile.coverage_bias_rate) - hist_cov_avg, 6)
        else:
            # New outlet — compare against current cross-outlet mean as baseline
            baseline_used_runs = 0
            omission_score = round(float(profile.coverage_bias_rate) - cross_outlet_coverage_mean, 6)

        systematic_omission = omission_score > OMISSION_THRESHOLD

        db.add(
            models.OutletBiasSnapshot(
                outlet=profile.outlet,
                run_id=run_id,
                snapshot_date=now,
                sentiment_bias_avg=profile.sentiment_bias_avg,
                sentiment_score_avg=profile.sentiment_score_avg,
                articles_scored=profile.articles_scored,
                topics_covered=profile.topics_covered,
                topics_considered=profile.topics_considered,
                coverage_missing_majority=profile.coverage_missing_majority,
                coverage_bias_rate=profile.coverage_bias_rate,
                coverage_bias_rate_soft=profile.coverage_bias_rate_soft,
                missed_topics=profile.missed_topics,
                emphasis_bias_avg=profile.emphasis_bias_avg,
                political_side_bias_avg=profile.political_side_bias_avg,
                government_sentiment_avg=profile.government_sentiment_avg,
                opposition_sentiment_avg=profile.opposition_sentiment_avg,
                political_actor_count=profile.political_actor_count,
                bsi_score=profile.bsi_score,
                source_trust_score=profile.source_trust_score,
                misinformation_risk_score=profile.misinformation_risk_score,
                bsi_confidence_low=profile.bsi_confidence_low,
                bsi_confidence_high=profile.bsi_confidence_high,
                article_count_per_topic_avg=profile.article_count_per_topic_avg,
                omission_score=omission_score,
                systematic_omission=systematic_omission,
                baseline_used_runs=baseline_used_runs,
            )
        )
