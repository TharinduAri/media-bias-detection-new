from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from api import models
from api.database import Base, db_manager

from .clusterer import (
    TopicClusterSpec,
    build_external_clusters,
    build_internal_clusters,
    dominant_outlet_share,
    get_dominant_outlet,
    normalize_external_clusters,
    stable_topic_key,
    MAX_DOMINANT_OUTLET_SHARE,
    MIN_TOPIC_OUTLETS,
)
from .embedder import (
    _resolve_embedding_model_name,
    load_analysis_rows,
    prepare_embeddings,
)
from .models_manager import SentimentResult, get_models
from .scorer import (
    COVERAGE_MAJORITY_THRESHOLD,
    build_profiles,
    compute_emphasis_bias,
    init_outlet_stats,
    insert_snapshots_with_omission,
    insert_topic_bsi_rows,
    upsert_article_bias_scores,
    upsert_profiles,
)
from .text_utils import _build_outlet_blocklist

# Re-exported for backward compatibility with api/routers/bias.py
__all__ = [
    "ensure_bias_tables",
    "get_models",
    "run_bias_analysis",
    "run_bias_analysis_with_clusters",
    "TopicClusterSpec",
    "SentimentResult",
]

DAYS_LOOKBACK = 28


def ensure_bias_tables(drop_first: bool = False) -> None:
    target_tables = [
        models.ArticleBiasScore.__table__,
        models.ArticleEmbedding.__table__,
        models.OutletBiasProfile.__table__,
        models.BiasRunLog.__table__,
        models.OutletBiasSnapshot.__table__,
        models.OutletTopicBSI.__table__,
    ]
    if drop_first:
        Base.metadata.drop_all(bind=db_manager.engine, tables=target_tables)
    Base.metadata.create_all(bind=db_manager.engine, tables=target_tables)


def run_bias_analysis(db: Session) -> Dict[str, object]:
    return _run_bias_analysis_impl(db=db, external_clusters=None)


def run_bias_analysis_with_clusters(
    db: Session,
    clusters: Iterable[Mapping[str, Any] | TopicClusterSpec],
) -> Dict[str, object]:
    normalized_clusters = normalize_external_clusters(clusters)
    return _run_bias_analysis_impl(db=db, external_clusters=normalized_clusters)


EMBEDDING_PROVIDER = "local"
EMBEDDING_MODEL_KEY = "mpnet_v2"


def _run_bias_analysis_impl(
    db: Session,
    external_clusters: List[TopicClusterSpec] | None,
) -> Dict[str, object]:
    started_at = datetime.utcnow()
    run_logs: List[str] = ["Bias analysis started..."]
    run_status = "done"
    run_error: str | None = None
    cluster_source = "external" if external_clusters is not None else "internal"

    try:
        ensure_bias_tables()

        since = datetime.utcnow() - timedelta(days=DAYS_LOOKBACK)
        recent_articles = _load_recent_articles(db, since)

        embedding_model = _resolve_embedding_model_name(EMBEDDING_PROVIDER, EMBEDDING_MODEL_KEY)
        run_logs.append(f"Cluster source: {cluster_source}")
        run_logs.append(f"Embedding model: {embedding_model}")
        run_logs.append(f"Recent articles found: {len(recent_articles)}")

        if not recent_articles:
            run_logs.append("No recent articles with enough text in the last 28 days.")
            _persist_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return _empty_result(0, embedding_model, cluster_source, external_clusters)

        outlets = [
            row[0]
            for row in db.query(distinct(models.Article.outlet)).filter(models.Article.date >= since).all()
        ]
        run_logs.append(f"Outlets in window: {len(outlets)}")

        outlet_blocklist = _build_outlet_blocklist(outlets)
        model_manager = get_models()
        embeddings_saved = prepare_embeddings(
            db=db,
            recent_articles=recent_articles,
            outlet_blocklist=outlet_blocklist,
            embedding_provider=EMBEDDING_PROVIDER,
            local_embedding_key=EMBEDDING_MODEL_KEY,
            embedding_model=embedding_model,
            model_manager=model_manager,
            run_logs=run_logs,
        )
        analysis_rows, embeddings = load_analysis_rows(
            db=db,
            recent_articles=recent_articles,
            outlet_blocklist=outlet_blocklist,
            embedding_provider=EMBEDDING_PROVIDER,
            embedding_model=embedding_model,
        )
        run_logs.append(f"Embeddings available for analysis: {len(analysis_rows)}")

        if len(analysis_rows) < 2:
            run_logs.append("Not enough articles to form topic groups.")
            _persist_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return _empty_result(embeddings_saved, embedding_model, cluster_source, external_clusters)

        analysis_articles = [row["article"] for row in analysis_rows]
        if external_clusters is None:
            clusters = build_internal_clusters(embeddings, analysis_articles, run_logs)
            topic_overrides: Dict[int, Dict[str, str | None]] = {}
            run_logs.append(f"Topic groups formed: {len(clusters)}")
        else:
            clusters, topic_overrides, ignored_clusters = build_external_clusters(
                external_clusters=external_clusters,
                analysis_articles=analysis_articles,
            )
            run_logs.append(f"External topic groups received: {len(external_clusters)}")
            run_logs.append(f"External topic groups accepted: {len(clusters)}")
            if ignored_clusters:
                run_logs.append(f"External topic groups ignored: {ignored_clusters}")

        if not clusters:
            run_logs.append("No valid topic groups available for scoring.")
            _persist_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return _empty_result(embeddings_saved, embedding_model, cluster_source, external_clusters)

        texts = [row["text"] for row in analysis_rows]
        sentiment_results = model_manager.analyze_sentiment(texts)
        run_logs.append("Computed sentiment scores.")
        run_logs.append(
            "Sentiment mix: "
            f"positive={sum(1 for r in sentiment_results if r.label == 'positive')}, "
            f"neutral={sum(1 for r in sentiment_results if r.label == 'neutral')}, "
            f"negative={sum(1 for r in sentiment_results if r.label == 'negative')}, "
            f"near_zero_score={sum(1 for r in sentiment_results if abs(r.score) < 1e-6)}"
        )

        now = datetime.utcnow()
        article_scores: List[models.ArticleBiasScore] = []
        outlet_stats = init_outlet_stats(outlets)
        outlet_topic_stats: Dict[str, Dict[str, Dict[str, Any]]] = {o: {} for o in outlets}
        topics_processed = 0
        skipped_single_outlet = 0
        skipped_low_diversity = 0
        skipped_outlet_dominance = 0

        for label, indices in clusters.items():
            cluster_outlets = {analysis_articles[idx].outlet for idx in indices}
            if len(cluster_outlets) < 2:
                skipped_single_outlet += len(indices)
                continue
            if len(cluster_outlets) < MIN_TOPIC_OUTLETS:
                skipped_low_diversity += len(indices)
                continue

            dom_share = dominant_outlet_share(indices, analysis_articles)
            is_dominated = dom_share > MAX_DOMINANT_OUTLET_SHARE

            cluster_vecs = embeddings[np.array(indices)]
            topic_override = topic_overrides.get(label, {})
            topic_label: str | None = topic_override.get("topic_label")
            topic_key: str | None = topic_override.get("topic_key")
            topic_titles = [analysis_articles[idx].title for idx in indices]
            if not topic_label:
                topic_label = model_manager.generate_topic_label(topic_titles, outlet_blocklist, cluster_vecs)
            if not topic_key:
                topic_key = stable_topic_key(cluster_vecs, analysis_articles, indices)

            coverage_ratio = len(cluster_outlets) / max(len(outlets), 1)
            coverage_majority = coverage_ratio >= COVERAGE_MAJORITY_THRESHOLD
            emphasis_biases = compute_emphasis_bias(indices, analysis_articles)

            def _record(idx: int, bias_score: float, ref_mean: float) -> None:
                article = analysis_articles[idx]
                sentiment = sentiment_results[idx]
                emph = emphasis_biases.get(idx, 0.0)
                article_scores.append(
                    models.ArticleBiasScore(
                        article_id=article.id,
                        outlet=article.outlet,
                        topic_key=topic_key,
                        topic_label=topic_label,
                        sentiment_label=sentiment.label,
                        sentiment_score=float(sentiment.score),
                        sentiment_confidence=float(sentiment.confidence),
                        sentiment_bias=float(bias_score),
                        group_sentiment_mean=float(ref_mean),
                        coverage_majority=coverage_majority,
                        coverage_present=True,
                        emphasis_bias=float(emph),
                        created_at=now,
                    )
                )
                stats = outlet_stats[article.outlet]
                stats["sentiment_bias_sum"] += bias_score
                stats["sentiment_score_sum"] += sentiment.score
                stats["emphasis_bias_sum"] += emph
                stats["articles_scored"] += 1
                t = outlet_topic_stats[article.outlet].setdefault(topic_key, {
                    "sentiment_bias_sum": 0.0,
                    "emphasis_bias_sum": 0.0,
                    "article_count": 0,
                    "topic_label": topic_label,
                    "coverage_present": True,
                })
                t["sentiment_bias_sum"] += bias_score
                t["emphasis_bias_sum"] += emph
                t["article_count"] += 1

            if is_dominated:
                dominant_outlet = get_dominant_outlet(indices, analysis_articles)
                dominant_idxs = [i for i in indices if analysis_articles[i].outlet == dominant_outlet]
                minority_idxs = [i for i in indices if analysis_articles[i].outlet != dominant_outlet]

                if not minority_idxs:
                    skipped_outlet_dominance += len(indices)
                    continue

                dominant_mean = float(np.mean([sentiment_results[i].score for i in dominant_idxs]))
                all_mean = float(np.mean([sentiment_results[i].score for i in indices]))

                topics_processed += 1
                for idx in minority_idxs:
                    _record(idx, sentiment_results[idx].score - dominant_mean, dominant_mean)
                for idx in dominant_idxs:
                    _record(idx, sentiment_results[idx].score - all_mean, all_mean)
            else:
                topics_processed += 1
                group_scores = [sentiment_results[idx].score for idx in indices]
                group_mean = float(np.mean(group_scores)) if group_scores else 0.0
                for idx in indices:
                    _record(idx, sentiment_results[idx].score - group_mean, group_mean)

            for outlet in cluster_outlets:
                outlet_stats[outlet]["topics_covered"] += 1

            if coverage_majority:
                for outlet in outlets:
                    stats = outlet_stats[outlet]
                    stats["topics_considered"] += 1
                    if outlet not in cluster_outlets:
                        stats["coverage_missing_majority"] += 1
                        stats["missed_topics"].append(topic_label)
                        outlet_topic_stats[outlet].setdefault(topic_key, {
                            "sentiment_bias_sum": 0.0,
                            "emphasis_bias_sum": 0.0,
                            "article_count": 0,
                            "topic_label": topic_label,
                            "coverage_present": False,
                        })["coverage_present"] = False

        if article_scores:
            article_scores_saved = upsert_article_bias_scores(db, article_scores)
            run_logs.append(f"Article bias scores saved: {article_scores_saved}")
        else:
            article_scores_saved = 0
            run_logs.append("No qualifying topic groups produced bias scores.")

        skipped_articles = len(analysis_rows) - article_scores_saved
        run_logs.append(f"Articles skipped total: {skipped_articles}")
        run_logs.append(
            "Skipped by reason: "
            f"single-outlet={skipped_single_outlet}, "
            f"low-diversity={skipped_low_diversity}, "
            f"outlet-dominance={skipped_outlet_dominance}"
        )

        log_row = _persist_run_log(
            db, started_at, datetime.utcnow(), run_status, run_error, run_logs, commit=False
        )
        run_id = log_row.id

        profiles, topic_bsi_rows = build_profiles(outlet_stats, outlet_topic_stats, now, run_id)
        profiles_updated = upsert_profiles(db, profiles)
        run_logs.append(f"Outlet profiles updated: {profiles_updated}")

        insert_snapshots_with_omission(db, profiles, run_id, now)
        insert_topic_bsi_rows(db, topic_bsi_rows)
        db.commit()

        return {
            "status": "ok",
            "message": "Bias analysis completed.",
            "processed_articles": article_scores_saved,
            "topics_processed": topics_processed,
            "profiles_updated": profiles_updated,
            "embeddings_saved": embeddings_saved,
            "embedding_provider": EMBEDDING_PROVIDER,
            "embedding_model": embedding_model,
            "cluster_source": cluster_source,
            "clusters_received": len(external_clusters) if external_clusters is not None else None,
        }
    except Exception as exc:
        run_status = "error"
        run_error = str(exc)
        run_logs.append(f"Error: {run_error}")
        db.rollback()
        _persist_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
        raise


def _load_recent_articles(db: Session, since: datetime) -> List[models.Article]:
    return (
        db.query(models.Article)
        .filter(models.Article.date >= since)
        .filter(models.Article.text.isnot(None))
        .filter(func.length(models.Article.text) > 100)
        .order_by(models.Article.date.desc())
        .all()
    )


def _persist_run_log(
    db: Session,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: str | None,
    log_lines: List[str],
    commit: bool = True,
) -> models.BiasRunLog:
    ensure_bias_tables()
    log_row = models.BiasRunLog(
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=error,
        log_lines=log_lines,
        created_at=datetime.utcnow(),
    )
    db.add(log_row)
    if commit:
        db.commit()
    else:
        db.flush()
    return log_row


def _empty_result(
    embeddings_saved: int,
    embedding_model: str,
    cluster_source: str,
    external_clusters: List[TopicClusterSpec] | None,
) -> Dict[str, object]:
    return {
        "status": "ok",
        "message": "No data to process.",
        "processed_articles": 0,
        "topics_processed": 0,
        "profiles_updated": 0,
        "embeddings_saved": embeddings_saved,
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": embedding_model,
        "cluster_source": cluster_source,
        "clusters_received": len(external_clusters) if external_clusters is not None else None,
    }
