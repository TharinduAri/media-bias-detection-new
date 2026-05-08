from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

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
) -> float:
    """Bias Signal Index [0-1]. Higher = more biased.

    BSI = 0.4 * clamp(|sentiment| / 0.5) + 0.4 * coverage_rate + 0.2 * clamp(|emphasis|)
    """
    s = min(abs(sentiment_bias_avg) / 0.5, 1.0)
    c = min(max(coverage_bias_rate, 0.0), 1.0)
    e = min(abs(emphasis_bias_avg), 1.0)
    return round(0.4 * s + 0.4 * c + 0.2 * e, 6)


def init_outlet_stats(outlets: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    return {
        outlet: {
            "sentiment_bias_sum": 0.0,
            "sentiment_score_sum": 0.0,
            "emphasis_bias_sum": 0.0,
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
) -> Dict[int, float]:
    """Relative article length vs. cluster mean, clamped to [-1, 1].

    Positive = outlet wrote more about this story than peers.
    """
    lengths: Dict[int, int] = {}
    for idx in indices:
        article = articles[idx]
        text = getattr(article, "clean_text", None) or getattr(article, "text", None) or ""
        lengths[idx] = len(text)

    if not lengths:
        return {idx: 0.0 for idx in indices}

    mean_len = float(np.mean(list(lengths.values())))
    if mean_len < 1.0:
        return {idx: 0.0 for idx in indices}

    return {
        idx: float(max(-1.0, min(1.0, (length - mean_len) / mean_len)))
        for idx, length in lengths.items()
    }


def build_profiles(
    outlet_stats: Dict[str, Dict[str, Any]],
    outlet_topic_stats: Dict[str, Dict[str, Dict[str, Any]]],
    now: datetime,
    run_id: int,
) -> Tuple[List[models.OutletBiasProfile], List[models.OutletTopicBSI]]:
    profiles: List[models.OutletBiasProfile] = []
    topic_bsi_rows: List[models.OutletTopicBSI] = []

    for outlet, stats in outlet_stats.items():
        articles_scored = int(stats["articles_scored"])
        topics_considered = int(stats["topics_considered"])
        sentiment_bias_avg = stats["sentiment_bias_sum"] / articles_scored if articles_scored else 0.0
        sentiment_score_avg = stats["sentiment_score_sum"] / articles_scored if articles_scored else 0.0
        emphasis_bias_avg = stats["emphasis_bias_sum"] / articles_scored if articles_scored else 0.0
        coverage_missing = int(stats["coverage_missing_majority"])
        coverage_bias_rate = coverage_missing / topics_considered if topics_considered else 0.0
        bsi = compute_bsi(sentiment_bias_avg, coverage_bias_rate, emphasis_bias_avg)

        profiles.append(
            models.OutletBiasProfile(
                outlet=outlet,
                sentiment_bias_avg=float(sentiment_bias_avg),
                sentiment_score_avg=float(sentiment_score_avg),
                emphasis_bias_avg=float(emphasis_bias_avg),
                articles_scored=articles_scored,
                topics_covered=int(stats["topics_covered"]),
                topics_considered=topics_considered,
                coverage_missing_majority=coverage_missing,
                coverage_bias_rate=float(coverage_bias_rate),
                missed_topics=stats["missed_topics"],
                bsi_score=float(bsi),
                updated_at=now,
            )
        )

        for t_key, t in outlet_topic_stats.get(outlet, {}).items():
            cnt = t["article_count"]
            t_sent = t["sentiment_bias_sum"] / cnt if cnt else 0.0
            t_emph = t["emphasis_bias_sum"] / cnt if cnt else 0.0
            t_cov_rate = 0.0 if t["coverage_present"] else 1.0
            topic_bsi_rows.append(
                models.OutletTopicBSI(
                    run_id=run_id,
                    outlet=outlet,
                    topic_key=t_key,
                    topic_label=t.get("topic_label"),
                    sentiment_bias_avg=float(t_sent),
                    emphasis_bias_avg=float(t_emph),
                    coverage_present=bool(t["coverage_present"]),
                    article_count=cnt,
                    bsi_score=compute_bsi(t_sent, t_cov_rate, t_emph),
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
            existing.missed_topics = profile.missed_topics
            existing.emphasis_bias_avg = profile.emphasis_bias_avg
            existing.bsi_score = profile.bsi_score
            existing.updated_at = profile.updated_at
        else:
            db.add(profile)
        updated += 1
    db.commit()
    return updated


def upsert_article_bias_scores(db: Session, scores: List[models.ArticleBiasScore]) -> int:
    deduped: Dict[int, models.ArticleBiasScore] = {}
    for score in scores:
        if score.article_id not in deduped:
            deduped[score.article_id] = score

    if not deduped:
        return 0

    existing_scores = (
        db.query(models.ArticleBiasScore)
        .filter(models.ArticleBiasScore.article_id.in_(deduped.keys()))
        .all()
    )
    existing_by_id = {s.article_id: s for s in existing_scores}

    for article_id, score in deduped.items():
        existing = existing_by_id.get(article_id)
        if existing:
            existing.outlet = score.outlet
            existing.topic_key = score.topic_key
            existing.topic_label = score.topic_label
            existing.sentiment_label = score.sentiment_label
            existing.sentiment_score = score.sentiment_score
            existing.sentiment_confidence = score.sentiment_confidence
            existing.sentiment_bias = score.sentiment_bias
            existing.group_sentiment_mean = score.group_sentiment_mean
            existing.coverage_majority = score.coverage_majority
            existing.coverage_present = score.coverage_present
            existing.emphasis_bias = score.emphasis_bias
            existing.created_at = score.created_at
        else:
            db.add(score)

    db.commit()
    return len(deduped)


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
            existing.coverage_present = row.coverage_present
            existing.article_count = row.article_count
            existing.bsi_score = row.bsi_score
            existing.topic_label = row.topic_label
        else:
            db.add(row)
    return len(rows)


def insert_snapshots_with_omission(
    db: Session,
    profiles: List[models.OutletBiasProfile],
    run_id: int,
    now: datetime,
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

        omission_score: float | None = None
        systematic_omission: bool | None = None
        baseline_used_runs: int | None = None

        if recent_snaps:
            baseline_used_runs = len(recent_snaps)
            hist_cov_avg = sum(s.coverage_bias_rate for s in recent_snaps) / baseline_used_runs
            omission_score = round(float(profile.coverage_bias_rate) - hist_cov_avg, 6)
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
                missed_topics=profile.missed_topics,
                emphasis_bias_avg=profile.emphasis_bias_avg,
                bsi_score=profile.bsi_score,
                omission_score=omission_score,
                systematic_omission=systematic_omission,
                baseline_used_runs=baseline_used_runs,
            )
        )
