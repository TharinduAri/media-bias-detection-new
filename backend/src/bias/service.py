from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Set

logger = logging.getLogger(__name__)

import numpy as np
from sqlalchemy import distinct, func, text
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
from .models_manager import SentimentResult, generate_labels_with_gemini, get_models
from .scorer import (
    COVERAGE_MAJORITY_THRESHOLD,
    build_profiles,
    compute_emphasis_bias,
    compute_soft_coverage_score,
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

# ── Live run state (in-memory, cleared on each new run) ──────────────────────

_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"running": False, "logs": [], "status": "idle"}


class _LiveLog(list):
    """List whose .append() mirrors each entry into the global run state."""
    def append(self, item: str) -> None:  # type: ignore[override]
        super().append(item)
        with _run_lock:
            _run_state["logs"] = list(self)


def get_run_state() -> Dict[str, Any]:
    with _run_lock:
        return {
            "running": _run_state["running"],
            "logs": list(_run_state["logs"]),
            "status": _run_state["status"],
        }


def _run_schema_migrations() -> None:
    """Idempotent ADD COLUMN migrations executed on every startup."""
    migrations = [
        'ALTER TABLE "ArticleBiasScore" ADD COLUMN IF NOT EXISTS dominant_outlet BOOLEAN DEFAULT FALSE',
        'ALTER TABLE "ArticleBiasScore" ADD COLUMN IF NOT EXISTS emphasis_length_bias FLOAT',
        'ALTER TABLE "ArticleBiasScore" ADD COLUMN IF NOT EXISTS emphasis_sentence_bias FLOAT',
        'ALTER TABLE "ArticleBiasScore" ADD COLUMN IF NOT EXISTS emphasis_entity_bias FLOAT',
        'ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS bsi_confidence_low FLOAT',
        'ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS bsi_confidence_high FLOAT',
        'ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS article_count_per_topic_avg FLOAT',
        'ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS coverage_bias_rate_soft FLOAT',
        'ALTER TABLE "OutletBiasSnapshot" ADD COLUMN IF NOT EXISTS bsi_confidence_low FLOAT',
        'ALTER TABLE "OutletBiasSnapshot" ADD COLUMN IF NOT EXISTS bsi_confidence_high FLOAT',
        'ALTER TABLE "OutletBiasSnapshot" ADD COLUMN IF NOT EXISTS article_count_per_topic_avg FLOAT',
        'ALTER TABLE "OutletBiasSnapshot" ADD COLUMN IF NOT EXISTS coverage_bias_rate_soft FLOAT',
        'ALTER TABLE "OutletTopicBSI" ADD COLUMN IF NOT EXISTS label_source VARCHAR(32)',
    ]
    with db_manager.engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()
    _migrate_article_bias_unique_constraint()


def _migrate_article_bias_unique_constraint() -> None:
    """Replace single-column unique constraint with composite (article_id, topic_key)."""
    with db_manager.engine.connect() as conn:
        try:
            conn.execute(text(
                'ALTER TABLE "ArticleBiasScore" DROP CONSTRAINT IF EXISTS uq_article_bias_article_id'
            ))
            conn.execute(text(
                'ALTER TABLE "ArticleBiasScore" ADD CONSTRAINT uq_article_bias_article_topic '
                'UNIQUE (article_id, topic_key)'
            ))
            conn.commit()
        except Exception:
            conn.rollback()


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
    _run_schema_migrations()
    Base.metadata.create_all(bind=db_manager.engine, tables=target_tables)


def run_bias_analysis(db: Session) -> Dict[str, object]:
    return _run_bias_analysis_impl(db=db, external_clusters=None, skip_embedding=False)


def run_bias_analysis_fast(db: Session) -> Dict[str, object]:
    """Skip embedding step — use whatever is already saved in ArticleEmbedding."""
    return _run_bias_analysis_impl(db=db, external_clusters=None, skip_embedding=True)


def run_bias_analysis_with_clusters(
    db: Session,
    clusters: Iterable[Mapping[str, Any] | TopicClusterSpec],
) -> Dict[str, object]:
    normalized_clusters = normalize_external_clusters(clusters)
    return _run_bias_analysis_impl(db=db, external_clusters=normalized_clusters, skip_embedding=False)


EMBEDDING_PROVIDER = "local"
EMBEDDING_MODEL_KEY = "mpnet_v2"


def _run_bias_analysis_impl(
    db: Session,
    external_clusters: List[TopicClusterSpec] | None,
    skip_embedding: bool = False,
) -> Dict[str, object]:
    started_at = datetime.utcnow()
    run_logs: _LiveLog = _LiveLog()
    run_status = "done"
    run_error: str | None = None
    cluster_source = "external" if external_clusters is not None else "internal"

    with _run_lock:
        _run_state.update({"running": True, "logs": [], "status": "running"})
    run_logs.append("Bias analysis started...")

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
        if skip_embedding:
            run_logs.append("Skipping embedding step — using saved embeddings.")
            embeddings_saved = 0
        else:
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
        outlet_score_arrays: Dict[str, Dict[str, List[float]]] = {
            o: {"sentiment_bias": [], "emphasis_bias": []} for o in outlets
        }
        # Collect per-cluster outlet sets and mainstream weights for soft coverage computation
        scored_cluster_outlet_sets: List[Set[str]] = []
        scored_cluster_mainstream_weights: List[float] = []
        topics_processed = 0
        skipped_single_outlet = 0
        skipped_low_diversity = 0
        skipped_outlet_dominance = 0

        # Build a list of clusters that will actually be scored (same filters as the loop)
        # so we can send one batched Gemini request for all their labels.
        cluster_items = list(clusters.items())
        scoreable = [
            (label, indices)
            for label, indices in cluster_items
            if len({analysis_articles[idx].outlet for idx in indices}) >= MIN_TOPIC_OUTLETS
            and not topic_overrides.get(label, {}).get("topic_label")
        ]
        cluster_title_batches = [
            [analysis_articles[idx].title for idx in indices]
            for _, indices in scoreable
        ]
        gemini_labels: List[str | None] = generate_labels_with_gemini(cluster_title_batches)
        gemini_label_map: Dict[int, str | None] = {
            label: gemini_labels[i] for i, (label, _) in enumerate(scoreable)
        }
        run_logs.append(
            f"Gemini label batch: {sum(1 for v in gemini_labels if v)} / {len(gemini_labels)} succeeded."
        )

        for label, indices in cluster_items:
            cluster_outlets = {analysis_articles[idx].outlet for idx in indices}
            if len(cluster_outlets) < 2:
                skipped_single_outlet += len(indices)
                continue
            if len(cluster_outlets) < MIN_TOPIC_OUTLETS:
                skipped_low_diversity += len(indices)
                continue

            dom_share = dominant_outlet_share(indices, analysis_articles)
            is_dominated = dom_share > MAX_DOMINANT_OUTLET_SHARE
            dominant_outlet_name: str | None = (
                get_dominant_outlet(indices, analysis_articles) if is_dominated else None
            )

            # Skip clusters that are wholly single-outlet after dominance check
            if is_dominated and dominant_outlet_name:
                minority_idxs = [i for i in indices if analysis_articles[i].outlet != dominant_outlet_name]
                if not minority_idxs:
                    skipped_outlet_dominance += len(indices)
                    continue

            cluster_vecs = embeddings[np.array(indices)]
            topic_override = topic_overrides.get(label, {})
            topic_label: str = topic_override.get("topic_label") or ""
            label_source: str = "override"
            topic_key: str | None = topic_override.get("topic_key")
            topic_titles = [analysis_articles[idx].title for idx in indices]
            if not topic_label:
                gemini_label = gemini_label_map.get(label)
                topic_label, label_source = model_manager.generate_topic_label(
                    topic_titles, outlet_blocklist, cluster_vecs, gemini_label=gemini_label
                )
                logger.info("Topic '%s' label_source=%s", topic_label, label_source)
            if not topic_key:
                topic_key = stable_topic_key(cluster_vecs, analysis_articles, indices)

            coverage_ratio = len(cluster_outlets) / max(len(outlets), 1)
            coverage_majority = coverage_ratio >= COVERAGE_MAJORITY_THRESHOLD
            emphasis_biases = compute_emphasis_bias(indices, analysis_articles)

            # Always use group mean as reference for all outlets (Fix 2 — symmetric baseline)
            group_mean = float(np.mean([sentiment_results[idx].score for idx in indices]))
            topics_processed += 1

            def _record(idx: int, is_dominant_outlet: bool = False) -> None:
                article = analysis_articles[idx]
                sentiment = sentiment_results[idx]
                emph_dict = emphasis_biases.get(idx, {
                    "emphasis_bias": 0.0, "length_bias": 0.0,
                    "sentence_bias": 0.0, "entity_bias": 0.0,
                })
                bias_score = float(sentiment.score - group_mean)
                emph = float(emph_dict["emphasis_bias"])
                article_scores.append(
                    models.ArticleBiasScore(
                        article_id=article.id,
                        outlet=article.outlet,
                        topic_key=topic_key,
                        topic_label=topic_label,
                        sentiment_label=sentiment.label,
                        sentiment_score=float(sentiment.score),
                        sentiment_confidence=float(sentiment.confidence),
                        sentiment_bias=bias_score,
                        group_sentiment_mean=group_mean,
                        coverage_majority=coverage_majority,
                        coverage_present=True,
                        emphasis_bias=emph,
                        dominant_outlet=is_dominant_outlet,
                        emphasis_length_bias=float(emph_dict["length_bias"]),
                        emphasis_sentence_bias=float(emph_dict["sentence_bias"]),
                        emphasis_entity_bias=float(emph_dict["entity_bias"]),
                        created_at=now,
                    )
                )
                stats = outlet_stats[article.outlet]
                stats["sentiment_bias_sum"] += bias_score
                stats["sentiment_score_sum"] += sentiment.score
                stats["emphasis_bias_sum"] += emph
                stats["articles_scored"] += 1
                outlet_score_arrays[article.outlet]["sentiment_bias"].append(bias_score)
                outlet_score_arrays[article.outlet]["emphasis_bias"].append(emph)
                t = outlet_topic_stats[article.outlet].setdefault(topic_key, {
                    "sentiment_bias_sum": 0.0,
                    "emphasis_bias_sum": 0.0,
                    "article_count": 0,
                    "topic_label": topic_label,
                    "label_source": label_source,
                    "coverage_present": True,
                })
                t["sentiment_bias_sum"] += bias_score
                t["emphasis_bias_sum"] += emph
                t["article_count"] += 1

            for idx in indices:
                is_dom = (dominant_outlet_name is not None and
                          analysis_articles[idx].outlet == dominant_outlet_name)
                _record(idx, is_dominant_outlet=is_dom)

            for outlet in cluster_outlets:
                outlet_stats[outlet]["topics_covered"] += 1

            # Track cluster for soft coverage score computation
            scored_cluster_outlet_sets.append(cluster_outlets)
            scored_cluster_mainstream_weights.append(coverage_ratio)

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
                            "label_source": label_source,
                            "coverage_present": False,
                        })["coverage_present"] = False

        # Compute soft coverage score per outlet
        outlet_soft_coverage: Dict[str, float] = {
            outlet: compute_soft_coverage_score(
                outlet, outlets, scored_cluster_outlet_sets, scored_cluster_mainstream_weights
            )
            for outlet in outlets
        }

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

        profiles, topic_bsi_rows = build_profiles(
            outlet_stats, outlet_topic_stats, now, run_id,
            outlet_score_arrays=outlet_score_arrays,
            outlet_soft_coverage=outlet_soft_coverage,
        )
        profiles_updated = upsert_profiles(db, profiles)
        run_logs.append(f"Outlet profiles updated: {profiles_updated}")

        cross_outlet_mean = (
            float(np.mean([p.coverage_bias_rate for p in profiles])) if profiles else 0.0
        )
        insert_snapshots_with_omission(db, profiles, run_id, now,
                                       cross_outlet_coverage_mean=cross_outlet_mean)
        insert_topic_bsi_rows(db, topic_bsi_rows)
        db.commit()

        run_logs.append("Done.")
        with _run_lock:
            _run_state.update({"running": False, "status": "done"})

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
        with _run_lock:
            _run_state.update({"running": False, "status": "error"})
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
