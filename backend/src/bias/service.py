from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Dict, Iterable, List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
from keybert import KeyBERT
from sqlalchemy import distinct, exists, func
from sqlalchemy.orm import Session

from api import models
from api.database import Base, db_manager

DAYS_LOOKBACK = 28
CLUSTER_DISTANCE_THRESHOLD = 0.6
COVERAGE_MAJORITY_THRESHOLD = 0.6
SENTIMENT_MAX_LENGTH = 256
MERGE_SIMILARITY_THRESHOLD = 0.5


@dataclass(frozen=True)
class SentimentResult:
    label: str
    confidence: float
    score: float


class BiasModelManager:
    def __init__(self) -> None:
        self.embedding_model_name = "all-MiniLM-L6-v2"
        self.sentiment_model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"
        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        tokenizer = AutoTokenizer.from_pretrained(self.sentiment_model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.sentiment_model_name)
        self.sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            device=-1,
        )
        self.kw_model = KeyBERT(model=self.embedding_model)

    def embed(self, texts: List[str]) -> np.ndarray:
        return np.asarray(self.embedding_model.encode(texts, normalize_embeddings=True))

    def analyze_sentiment(self, texts: List[str]) -> List[SentimentResult]:
        results = self.sentiment_pipeline(texts, truncation=True, max_length=SENTIMENT_MAX_LENGTH)
        mapped: List[SentimentResult] = []
        for item in results:
            label = str(item.get("label", "neutral")).lower()
            confidence = float(item.get("score", 0.0))
            mapped.append(
                SentimentResult(label=label, confidence=confidence, score=_label_to_score(label, confidence))
            )
        return mapped

    def generate_topic_label(self, titles: List[str]) -> str:
        if not titles:
            return "Unknown Topic"
        
        try:
            combined_text = " ".join(titles)
            # Extract single most representative 2-4 word keyphrase
            keywords = self.kw_model.extract_keywords(
                combined_text, 
                keyphrase_ngram_range=(2, 4), 
                stop_words='english', 
                top_n=1
            )
            
            if keywords:
                label = keywords[0][0]
                return label.title()
            
            # Fallback: first title truncated
            return titles[0][:50].strip().title()
        except Exception:
            return titles[0][:50].strip().title()


_MODEL_MANAGER: BiasModelManager | None = None


def get_models() -> BiasModelManager:
    global _MODEL_MANAGER
    if _MODEL_MANAGER is None:
        _MODEL_MANAGER = BiasModelManager()
    return _MODEL_MANAGER


def ensure_bias_tables(drop_first: bool = False) -> None:
    target_tables = [
        models.ArticleBiasScore.__table__,
        models.OutletBiasProfile.__table__,
        models.BiasRunLog.__table__,
    ]
    if drop_first:
        Base.metadata.drop_all(bind=db_manager.engine, tables=target_tables)
    
    Base.metadata.create_all(bind=db_manager.engine, tables=target_tables)


def run_bias_analysis(db: Session) -> Dict[str, object]:
    started_at = datetime.utcnow()
    run_logs: List[str] = ["Bias analysis started..."]
    run_status = "done"
    run_error: str | None = None

    try:
        ensure_bias_tables()

        since = datetime.utcnow() - timedelta(days=DAYS_LOOKBACK)
        unscored_articles = (
            db.query(models.Article)
            .filter(models.Article.date >= since)
            .filter(models.Article.text.isnot(None))
            .filter(func.length(models.Article.text) > 100)
            .filter(~exists().where(models.ArticleBiasScore.article_id == models.Article.id))
            .order_by(models.Article.date.desc())
            .all()
        )

        run_logs.append(f"Unscored articles found: {len(unscored_articles)}")

        if not unscored_articles:
            run_logs.append("No unscored articles in the last 28 days.")
            _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return {
                "status": "ok",
                "message": "No unscored articles found in the last 28 days.",
                "processed_articles": 0,
                "topics_processed": 0,
                "profiles_updated": 0,
            }

        outlets = [
            row[0]
            for row in db.query(distinct(models.Article.outlet)).filter(models.Article.date >= since).all()
        ]
        run_logs.append(f"Outlets in window: {len(outlets)}")

        texts = [_build_article_text(article) for article in unscored_articles]
        model_manager = get_models()
        embeddings = model_manager.embed(texts)
        run_logs.append("Computed sentence embeddings.")

        if len(unscored_articles) < 2:
            run_logs.append("Not enough articles to form topic groups.")
            _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return {
                "status": "ok",
                "message": "Not enough articles to form topic groups.",
                "processed_articles": 0,
                "topics_processed": 0,
                "profiles_updated": 0,
            }

        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(embeddings)
        clusters = _group_by_label(labels)
        run_logs.append(f"Topic groups formed: {len(clusters)}")

        clusters, merge_stats = _merge_single_outlet_clusters(clusters, embeddings, unscored_articles)
        if merge_stats["merged_clusters"]:
            run_logs.append(
                "Merged single-outlet clusters: "
                f"{merge_stats['merged_clusters']} (articles merged: {merge_stats['merged_articles']})"
            )

        sentiment_results = model_manager.analyze_sentiment(texts)
        run_logs.append("Computed sentiment scores.")

        now = datetime.utcnow()
        run_key = now.strftime("%Y%m%d%H%M%S")

        article_scores: List[models.ArticleBiasScore] = []
        outlet_stats = _init_outlet_stats(outlets)
        topics_processed = 0

        for label, indices in clusters.items():
            cluster_outlets = {unscored_articles[idx].outlet for idx in indices}
            if len(cluster_outlets) < 2:
                continue

            topics_processed += 1
            group_scores = [sentiment_results[idx].score for idx in indices]
            group_mean = float(np.mean(group_scores)) if group_scores else 0.0
            coverage_ratio = len(cluster_outlets) / max(len(outlets), 1)
            coverage_majority = coverage_ratio >= COVERAGE_MAJORITY_THRESHOLD
            
            # Generate human-readable label
            topic_titles = [unscored_articles[idx].title for idx in indices]
            topic_label = model_manager.generate_topic_label(topic_titles)
            
            topic_key = f"{run_key}-{label}"

            for idx in indices:
                article = unscored_articles[idx]
                sentiment = sentiment_results[idx]
                bias_score = sentiment.score - group_mean
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
                        group_sentiment_mean=float(group_mean),
                        coverage_majority=coverage_majority,
                        coverage_present=True,
                        created_at=now,
                    )
                )
                stats = outlet_stats[article.outlet]
                stats["sentiment_bias_sum"] += bias_score
                stats["sentiment_score_sum"] += sentiment.score
                stats["articles_scored"] += 1

            # Count unique topics covered by each outlet
            for outlet in cluster_outlets:
                outlet_stats[outlet]["topics_covered"] += 1

            if coverage_majority:
                for outlet in outlets:
                    stats = outlet_stats[outlet]
                    stats["topics_considered"] += 1
                    if outlet not in cluster_outlets:
                        stats["coverage_missing_majority"] += 1
                        stats["missed_topics"].append(topic_label)

        if article_scores:
            db.add_all(article_scores)
            db.commit()
            run_logs.append(f"Article bias scores saved: {len(article_scores)}")
        else:
            run_logs.append("No qualifying topic groups produced bias scores.")

        skipped_articles = len(unscored_articles) - len(article_scores)
        run_logs.append(f"Articles skipped due to single-outlet topics: {skipped_articles}")

        profiles = _build_profiles(outlet_stats, now)
        profiles_updated = _upsert_profiles(db, profiles)
        run_logs.append(f"Outlet profiles updated: {profiles_updated}")

        _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)

        return {
            "status": "ok",
            "message": "Bias analysis completed.",
            "processed_articles": len(article_scores),
            "topics_processed": topics_processed,
            "profiles_updated": profiles_updated,
        }
    except Exception as exc:
        run_status = "error"
        run_error = str(exc)
        run_logs.append(f"Error: {run_error}")
        _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
        raise


def _build_profiles(outlet_stats: Dict[str, Dict[str, float]], now: datetime) -> List[models.OutletBiasProfile]:
    profiles: List[models.OutletBiasProfile] = []
    for outlet, stats in outlet_stats.items():
        articles_scored = int(stats["articles_scored"])
        topics_considered = int(stats["topics_considered"])
        sentiment_bias_avg = stats["sentiment_bias_sum"] / articles_scored if articles_scored else 0.0
        sentiment_score_avg = stats["sentiment_score_sum"] / articles_scored if articles_scored else 0.0
        coverage_missing = int(stats["coverage_missing_majority"])
        coverage_bias_rate = coverage_missing / topics_considered if topics_considered else 0.0
        profiles.append(
            models.OutletBiasProfile(
                outlet=outlet,
                sentiment_bias_avg=float(sentiment_bias_avg),
                sentiment_score_avg=float(sentiment_score_avg),
                articles_scored=articles_scored,
                topics_covered=int(stats["topics_covered"]),
                topics_considered=topics_considered,
                coverage_missing_majority=coverage_missing,
                coverage_bias_rate=float(coverage_bias_rate),
                missed_topics=stats["missed_topics"],
                updated_at=now,
            )
        )
    return profiles


def _upsert_profiles(db: Session, profiles: Iterable[models.OutletBiasProfile]) -> int:
    updated = 0
    for profile in profiles:
        existing = db.query(models.OutletBiasProfile).filter(models.OutletBiasProfile.outlet == profile.outlet).first()
        if existing:
            existing.sentiment_bias_avg = profile.sentiment_bias_avg
            existing.sentiment_score_avg = profile.sentiment_score_avg
            existing.articles_scored = profile.articles_scored
            existing.topics_covered = profile.topics_covered
            existing.topics_considered = profile.topics_considered
            existing.coverage_missing_majority = profile.coverage_missing_majority
            existing.coverage_bias_rate = profile.coverage_bias_rate
            existing.missed_topics = profile.missed_topics
            existing.updated_at = profile.updated_at
        else:
            db.add(profile)
        updated += 1
    db.commit()
    return updated


def _group_by_label(labels: np.ndarray) -> Dict[int, List[int]]:
    grouped: Dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(idx)
    return grouped


def _build_article_text(article: models.Article) -> str:
    title = (article.title or "").strip()
    sentences = article.sentences if isinstance(article.sentences, list) else []
    snippet = ""
    if sentences:
        snippet = " ".join([s.strip() for s in sentences[:3] if s])
    else:
        source_text = (article.clean_text or article.text or "").strip()
        snippet = _first_sentences_from_text(source_text, 3)

    if snippet:
        return f"{title}. {snippet}" if title else snippet
    return title


def _first_sentences_from_text(text: str, limit: int) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(part.strip() for part in parts[:limit] if part.strip())


def _label_to_score(label: str, confidence: float) -> float:
    normalized = label.lower()
    if "positive" in normalized:
        return confidence
    if "negative" in normalized:
        return -confidence
    return 0.0


def _init_outlet_stats(outlets: Iterable[str]) -> Dict[str, Dict[str, float]]:
    return {
        outlet: {
            "sentiment_bias_sum": 0.0,
            "sentiment_score_sum": 0.0,
            "articles_scored": 0.0,
            "topics_covered": 0.0,
            "topics_considered": 0.0,
            "coverage_missing_majority": 0.0,
            "missed_topics": [],
        }
        for outlet in outlets
    }


def _merge_single_outlet_clusters(
    clusters: Dict[int, List[int]],
    embeddings: np.ndarray,
    articles: List[models.Article],
) -> Tuple[Dict[int, List[int]], Dict[str, int]]:
    merged_clusters = 0
    merged_articles = 0
    cluster_items: Dict[int, Dict[str, object]] = {}
    for label, indices in clusters.items():
        outlet_set = {articles[idx].outlet for idx in indices}
        centroid = np.mean(embeddings[indices], axis=0)
        cluster_items[label] = {"indices": list(indices), "outlets": outlet_set, "centroid": centroid}

    # Snapshot labels so we can safely mutate cluster_items during the merge loop.
    labels = list(cluster_items.keys())
    for label in labels:
        item = cluster_items[label]
        outlets = item["outlets"]
        if len(outlets) >= 2:
            continue

        best_label = None
        best_similarity = -1.0
        for candidate_label, candidate in cluster_items.items():
            if candidate_label == label:
                continue
            if outlets.intersection(candidate["outlets"]):
                continue
            similarity = _cosine_similarity(item["centroid"], candidate["centroid"])
            if similarity > best_similarity:
                best_similarity = similarity
                best_label = candidate_label

        if best_label is not None and best_similarity >= MERGE_SIMILARITY_THRESHOLD:
            target = cluster_items[best_label]
            target_indices = target["indices"]
            target_indices.extend(item["indices"])
            target["outlets"] = target["outlets"].union(outlets)
            target["centroid"] = np.mean(embeddings[target_indices], axis=0)
            merged_clusters += 1
            merged_articles += len(item["indices"])
            cluster_items.pop(label, None)

    merged: Dict[int, List[int]] = {
        label: item["indices"] for label, item in cluster_items.items()
    }
    return merged, {"merged_clusters": merged_clusters, "merged_articles": merged_articles}


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    norm_a = vec_a / (np.linalg.norm(vec_a) + 1e-8)
    norm_b = vec_b / (np.linalg.norm(vec_b) + 1e-8)
    return float(np.dot(norm_a, norm_b))


def _persist_bias_run_log(
    db: Session,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: str | None,
    log_lines: List[str],
) -> None:
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
    db.commit()
