from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import os
import re
from typing import Dict, Iterable, List, Set, Tuple

import httpx
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
from keybert import KeyBERT
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from api import models
from api.database import Base, db_manager

DAYS_LOOKBACK = 28
CLUSTER_DISTANCE_THRESHOLD = float(os.getenv("BIAS_CLUSTER_DISTANCE_THRESHOLD", "0.52"))
COVERAGE_MAJORITY_THRESHOLD = 0.6
SENTIMENT_MAX_LENGTH = 256
MERGE_SIMILARITY_THRESHOLD = 0.5
MAX_CLUSTER_SIZE = int(os.getenv("BIAS_MAX_CLUSTER_SIZE", "18"))
MIN_CLUSTER_CENTROID_SIMILARITY = float(os.getenv("BIAS_MIN_CLUSTER_CENTROID_SIMILARITY", "0.42"))
MAX_SPLIT_DEPTH = int(os.getenv("BIAS_MAX_SPLIT_DEPTH", "3"))
MIN_TOPIC_OUTLETS = int(os.getenv("BIAS_MIN_TOPIC_OUTLETS", "3"))
MAX_DOMINANT_OUTLET_SHARE = float(os.getenv("BIAS_MAX_DOMINANT_OUTLET_SHARE", "0.6"))
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
GEMINI_BATCH_SIZE = 32
LOCAL_EMBEDDING_MODELS: Dict[str, str] = {
    "minilm_l6": "all-MiniLM-L6-v2",
    "minilm_l12": "all-MiniLM-L12-v2",
    "mpnet_v2": "all-mpnet-base-v2",
    "multilingual_minilm": "paraphrase-multilingual-MiniLM-L12-v2",
}


@dataclass(frozen=True)
class SentimentResult:
    label: str
    confidence: float
    score: float


class BiasModelManager:
    def __init__(self, embedding_model_name: str) -> None:
        self.embedding_model_name = embedding_model_name
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

    def generate_topic_label(self, titles: List[str], outlet_blocklist: Set[str]) -> str:
        if not titles:
            return "Unknown Topic"
        
        try:
            cleaned_titles = [_strip_outlet_markers(t or "", outlet_blocklist) for t in titles]
            cleaned_titles = [t for t in cleaned_titles if t]
            if not cleaned_titles:
                return "General News"

            combined_text = " ".join(cleaned_titles)
            # Extract single most representative 2-4 word keyphrase
            keywords = self.kw_model.extract_keywords(
                combined_text, 
                keyphrase_ngram_range=(2, 4), 
                stop_words='english', 
                top_n=6
            )
            
            if keywords:
                for keyphrase, _ in keywords:
                    label = _sanitize_topic_label(str(keyphrase), outlet_blocklist)
                    if label:
                        return label.title()
            
            # Fallback: first title truncated
            fallback = _sanitize_topic_label(cleaned_titles[0][:60].strip(), outlet_blocklist)
            return (fallback or "General News").title()
        except Exception:
            fallback_src = titles[0] if titles else ""
            fallback = _sanitize_topic_label(fallback_src[:60].strip(), outlet_blocklist)
            return (fallback or "General News").title()


_MODEL_MANAGERS: Dict[str, BiasModelManager] = {}


def get_models(local_embedding_key: str = "minilm_l6") -> BiasModelManager:
    model_name = _resolve_local_embedding_model(local_embedding_key)
    manager = _MODEL_MANAGERS.get(model_name)
    if manager is None:
        manager = BiasModelManager(model_name)
        _MODEL_MANAGERS[model_name] = manager
    return manager


def ensure_bias_tables(drop_first: bool = False) -> None:
    target_tables = [
        models.ArticleBiasScore.__table__,
        models.ArticleEmbedding.__table__,
        models.OutletBiasProfile.__table__,
        models.BiasRunLog.__table__,
    ]
    if drop_first:
        Base.metadata.drop_all(bind=db_manager.engine, tables=target_tables)
    
    Base.metadata.create_all(bind=db_manager.engine, tables=target_tables)


def run_bias_analysis(
    db: Session,
    embedding_provider: str = "local",
    local_embedding_key: str = "minilm_l6",
) -> Dict[str, object]:
    started_at = datetime.utcnow()
    run_logs: List[str] = ["Bias analysis started..."]
    run_status = "done"
    run_error: str | None = None

    try:
        ensure_bias_tables()

        since = datetime.utcnow() - timedelta(days=DAYS_LOOKBACK)
        recent_articles = (
            db.query(models.Article)
            .filter(models.Article.date >= since)
            .filter(models.Article.text.isnot(None))
            .filter(func.length(models.Article.text) > 100)
            .order_by(models.Article.date.desc())
            .all()
        )

        embedding_model = _resolve_embedding_model_name(embedding_provider, local_embedding_key)
        run_logs.append(f"Embedding provider: {embedding_provider}")
        run_logs.append(f"Embedding model: {embedding_model}")
        run_logs.append(f"Recent articles found: {len(recent_articles)}")

        if not recent_articles:
            run_logs.append("No recent articles with enough text in the last 28 days.")
            _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return {
                "status": "ok",
                "message": "No recent articles found in the last 28 days.",
                "processed_articles": 0,
                "topics_processed": 0,
                "profiles_updated": 0,
                "embeddings_saved": 0,
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
            }

        outlets = [
            row[0]
            for row in db.query(distinct(models.Article.outlet)).filter(models.Article.date >= since).all()
        ]
        run_logs.append(f"Outlets in window: {len(outlets)}")

        outlet_blocklist = _build_outlet_blocklist(outlets)
        model_manager = get_models(local_embedding_key)
        embeddings_saved = _prepare_embeddings_for_recent_articles(
            db=db,
            recent_articles=recent_articles,
            outlet_blocklist=outlet_blocklist,
            embedding_provider=embedding_provider,
            local_embedding_key=local_embedding_key,
            embedding_model=embedding_model,
            model_manager=model_manager,
            run_logs=run_logs,
        )
        analysis_rows, embeddings = _load_analysis_rows_from_embeddings(
            db=db,
            recent_articles=recent_articles,
            outlet_blocklist=outlet_blocklist,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        run_logs.append(f"Embeddings available for analysis: {len(analysis_rows)}")

        if len(analysis_rows) < 2:
            run_logs.append("Not enough articles to form topic groups.")
            _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)
            return {
                "status": "ok",
                "message": "Not enough articles to form topic groups.",
                "processed_articles": 0,
                "topics_processed": 0,
                "profiles_updated": 0,
                "embeddings_saved": embeddings_saved,
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
            }

        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(embeddings)
        clusters = _group_by_label(labels)
        clusters = _refine_clusters_for_coherence(clusters, embeddings)
        analysis_articles = [row["article"] for row in analysis_rows]
        clusters = _split_outlet_dominated_clusters(clusters, analysis_articles)
        run_logs.append(f"Topic groups formed: {len(clusters)}")

        clusters, merge_stats = _merge_single_outlet_clusters(clusters, embeddings, analysis_articles)
        if merge_stats["merged_clusters"]:
            run_logs.append(
                "Merged single-outlet clusters: "
                f"{merge_stats['merged_clusters']} (articles merged: {merge_stats['merged_articles']})"
            )

        texts = [row["text"] for row in analysis_rows]
        sentiment_results = model_manager.analyze_sentiment(texts)
        run_logs.append("Computed sentiment scores.")

        now = datetime.utcnow()
        run_key = now.strftime("%Y%m%d%H%M%S")

        article_scores: List[models.ArticleBiasScore] = []
        outlet_stats = _init_outlet_stats(outlets)
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

            dominant_share = _dominant_outlet_share(indices, analysis_articles)
            if dominant_share > MAX_DOMINANT_OUTLET_SHARE:
                skipped_outlet_dominance += len(indices)
                continue

            topics_processed += 1
            group_scores = [sentiment_results[idx].score for idx in indices]
            group_mean = float(np.mean(group_scores)) if group_scores else 0.0
            coverage_ratio = len(cluster_outlets) / max(len(outlets), 1)
            coverage_majority = coverage_ratio >= COVERAGE_MAJORITY_THRESHOLD
            
            # Generate human-readable label
            topic_titles = [analysis_articles[idx].title for idx in indices]
            topic_label = model_manager.generate_topic_label(topic_titles, outlet_blocklist)
            
            topic_key = f"{run_key}-{label}"

            for idx in indices:
                article = analysis_articles[idx]
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
            article_scores_saved = _upsert_article_bias_scores(db, article_scores)
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

        profiles = _build_profiles(outlet_stats, now)
        profiles_updated = _upsert_profiles(db, profiles)
        run_logs.append(f"Outlet profiles updated: {profiles_updated}")

        _persist_bias_run_log(db, started_at, datetime.utcnow(), run_status, run_error, run_logs)

        return {
            "status": "ok",
            "message": "Bias analysis completed.",
            "processed_articles": article_scores_saved,
            "topics_processed": topics_processed,
            "profiles_updated": profiles_updated,
            "embeddings_saved": embeddings_saved,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
        }
    except Exception as exc:
        run_status = "error"
        run_error = str(exc)
        run_logs.append(f"Error: {run_error}")
        db.rollback()
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


def _resolve_local_embedding_model(local_embedding_key: str) -> str:
    key = (local_embedding_key or "minilm_l6").strip().lower()
    if key not in LOCAL_EMBEDDING_MODELS:
        supported = ", ".join(sorted(LOCAL_EMBEDDING_MODELS.keys()))
        raise ValueError(f"Unsupported local embedding key '{local_embedding_key}'. Supported: {supported}")
    return LOCAL_EMBEDDING_MODELS[key]


def _resolve_embedding_model_name(embedding_provider: str, local_embedding_key: str) -> str:
    provider = (embedding_provider or "local").strip().lower()
    if provider == "local":
        return _resolve_local_embedding_model(local_embedding_key)
    if provider == "gemini":
        return GEMINI_EMBED_MODEL
    raise ValueError(f"Unsupported embedding provider: {embedding_provider}")


def _embed_texts(
    texts: List[str],
    embedding_provider: str,
    local_embedding_key: str,
    model_manager: BiasModelManager,
) -> np.ndarray:
    provider = (embedding_provider or "local").strip().lower()
    if provider == "local":
        # Ensure requested local model key is valid even if manager was pre-initialized.
        _resolve_local_embedding_model(local_embedding_key)
        return model_manager.embed(texts)
    if provider == "gemini":
        return _embed_with_gemini(texts)
    raise ValueError(f"Unsupported embedding provider: {embedding_provider}")


def _embed_with_gemini(texts: List[str]) -> np.ndarray:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    candidate_models = _gemini_candidate_models(client_headers=headers)
    errors: List[str] = []

    with httpx.Client(timeout=60.0) as client:
        for model_name in candidate_models:
            try:
                embeddings = _embed_with_gemini_model(client, headers, texts, model_name)
                return np.asarray(embeddings, dtype=np.float32)
            except RuntimeError as exc:
                errors.append(str(exc))
                continue

    tried = ", ".join(candidate_models)
    failure_details = " | ".join(errors) if errors else "unknown error"
    raise RuntimeError(
        f"Gemini embedding failed for models [{tried}]. Errors: {failure_details}"
    )


def _embed_with_gemini_model(
    client: httpx.Client,
    headers: Dict[str, str],
    texts: List[str],
    model_name: str,
) -> List[List[float]]:
    model_embeddings: List[List[float]] = []
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:batchEmbedContents"
    for start in range(0, len(texts), GEMINI_BATCH_SIZE):
        chunk = texts[start : start + GEMINI_BATCH_SIZE]
        payload = {
            "requests": [
                {
                    "model": model_name,
                    "content": {"parts": [{"text": text}]},
                    "taskType": "SEMANTIC_SIMILARITY",
                }
                for text in chunk
            ]
        }
        response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"{model_name} failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        chunk_embeddings = data.get("embeddings", [])
        if len(chunk_embeddings) != len(chunk):
            raise RuntimeError(f"{model_name} response size mismatch.")
        for item in chunk_embeddings:
            vector = item.get("values")
            if not vector:
                raise RuntimeError(f"{model_name} response missing vector values.")
            model_embeddings.append(vector)
    return model_embeddings


def _gemini_candidate_models(client_headers: Dict[str, str]) -> List[str]:
    configured = GEMINI_EMBED_MODEL.strip()
    defaults = [
        "models/gemini-embedding-001",
        "models/gemini-embedding-2-preview",
        "models/gemini-embedding-2",
        "models/text-embedding-004",
    ]
    discovered = _discover_gemini_embed_models(client_headers)
    models = [configured] + discovered + defaults
    deduped: List[str] = []
    for model in models:
        if model and model not in deduped:
            deduped.append(model)
    return deduped


def _discover_gemini_embed_models(headers: Dict[str, str]) -> List[str]:
    api_key = headers.get("x-goog-api-key", "").strip()
    if not api_key:
        return []
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    params = {"key": api_key}
    methods_needed = {"embedContent", "batchEmbedContents"}
    discovered: List[str] = []
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers={"Content-Type": "application/json"}, params=params)
            if response.status_code >= 400:
                return []
            data = response.json()
            models = data.get("models", [])
            for model in models:
                name = str(model.get("name", "")).strip()
                methods = set(model.get("supportedGenerationMethods", []) or [])
                if name and methods.intersection(methods_needed):
                    discovered.append(name)
    except Exception:
        return []
    return discovered


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


def _upsert_article_bias_scores(db: Session, scores: List[models.ArticleBiasScore]) -> int:
    deduped_scores: Dict[int, models.ArticleBiasScore] = {}
    for score in scores:
        if score.article_id not in deduped_scores:
            deduped_scores[score.article_id] = score

    if not deduped_scores:
        return 0

    existing_scores = (
        db.query(models.ArticleBiasScore)
        .filter(models.ArticleBiasScore.article_id.in_(deduped_scores.keys()))
        .all()
    )
    existing_by_article_id = {score.article_id: score for score in existing_scores}

    for article_id, score in deduped_scores.items():
        existing = existing_by_article_id.get(article_id)
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
            existing.created_at = score.created_at
        else:
            db.add(score)

    db.commit()
    return len(deduped_scores)


def _prepare_embeddings_for_recent_articles(
    db: Session,
    recent_articles: List[models.Article],
    outlet_blocklist: Set[str],
    embedding_provider: str,
    local_embedding_key: str,
    embedding_model: str,
    model_manager: BiasModelManager,
    run_logs: List[str],
) -> int:
    texts = [_build_article_text(article, outlet_blocklist) for article in recent_articles]
    embeddings = _embed_texts(
        texts=texts,
        embedding_provider=embedding_provider,
        local_embedding_key=local_embedding_key,
        model_manager=model_manager,
    )
    run_logs.append("Computed sentence embeddings.")
    saved = _upsert_article_embeddings(
        db=db,
        articles=recent_articles,
        texts=texts,
        embeddings=embeddings,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        now=datetime.utcnow(),
    )
    run_logs.append(f"Article embeddings upserted: {saved}")
    return saved


def _load_analysis_rows_from_embeddings(
    db: Session,
    recent_articles: List[models.Article],
    outlet_blocklist: Set[str],
    embedding_provider: str,
    embedding_model: str,
) -> Tuple[List[Dict[str, object]], np.ndarray]:
    provider = (embedding_provider or "local").strip().lower()
    article_by_id: Dict[int, models.Article] = {article.id: article for article in recent_articles}
    if not article_by_id:
        return [], np.asarray([])

    embedding_rows = (
        db.query(models.ArticleEmbedding)
        .filter(models.ArticleEmbedding.article_id.in_(article_by_id.keys()))
        .filter(models.ArticleEmbedding.embedding_provider == provider)
        .filter(models.ArticleEmbedding.embedding_model == embedding_model)
        .all()
    )

    analysis_rows: List[Dict[str, object]] = []
    vectors: List[List[float]] = []
    for row in embedding_rows:
        article = article_by_id.get(row.article_id)
        vector_raw = row.embedding if isinstance(row.embedding, list) else []
        if article is None or not vector_raw:
            continue
        text = _build_article_text(article, outlet_blocklist)
        analysis_rows.append({"article": article, "text": text})
        vectors.append([float(v) for v in vector_raw])

    embeddings = np.asarray(vectors, dtype=np.float32)
    return analysis_rows, embeddings


def _upsert_article_embeddings(
    db: Session,
    articles: List[models.Article],
    texts: List[str],
    embeddings: np.ndarray,
    embedding_provider: str,
    embedding_model: str,
    now: datetime,
) -> int:
    if len(articles) != len(texts) or len(articles) != len(embeddings):
        raise RuntimeError("Article embedding inputs are misaligned.")

    saved = 0
    provider = (embedding_provider or "local").strip().lower()
    for article, text, vector in zip(articles, texts, embeddings):
        vector_list = [float(value) for value in np.asarray(vector, dtype=np.float32).tolist()]
        source_text_hash = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        existing = (
            db.query(models.ArticleEmbedding)
            .filter(models.ArticleEmbedding.article_id == article.id)
            .filter(models.ArticleEmbedding.embedding_provider == provider)
            .filter(models.ArticleEmbedding.embedding_model == embedding_model)
            .first()
        )
        if existing:
            existing.outlet = article.outlet or ""
            existing.embedding_dimensions = len(vector_list)
            existing.embedding = vector_list
            existing.source_text_hash = source_text_hash
            existing.updated_at = now
        else:
            db.add(
                models.ArticleEmbedding(
                    article_id=article.id,
                    outlet=article.outlet or "",
                    embedding_provider=provider,
                    embedding_model=embedding_model,
                    embedding_dimensions=len(vector_list),
                    embedding=vector_list,
                    source_text_hash=source_text_hash,
                    created_at=now,
                    updated_at=now,
                )
            )
        saved += 1

    db.commit()
    return saved


def _group_by_label(labels: np.ndarray) -> Dict[int, List[int]]:
    grouped: Dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(idx)
    return grouped


def _build_article_text(article: models.Article, outlet_blocklist: Set[str]) -> str:
    title = (article.title or "").strip()
    sentences = article.sentences if isinstance(article.sentences, list) else []
    snippet = ""
    if sentences:
        snippet = " ".join([s.strip() for s in sentences[:3] if s])
    else:
        source_text = (article.clean_text or article.text or "").strip()
        snippet = _first_sentences_from_text(source_text, 3)

    combined = f"{title}. {snippet}" if snippet and title else (snippet or title)
    return _strip_outlet_markers(combined, outlet_blocklist)


def _build_outlet_blocklist(outlets: List[str]) -> Set[str]:
    blocklist: Set[str] = set()
    for outlet in outlets:
        cleaned = (outlet or "").strip()
        if cleaned:
            blocklist.add(cleaned)
            blocklist.add(cleaned.replace(" ", ""))
            blocklist.add(cleaned.replace(" ", "-"))
            blocklist.add(cleaned.replace(" ", "_"))
    # Common domain-specific aliases/short forms.
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
        }
    )
    return {item for item in blocklist if item}


def _strip_outlet_markers(text: str, outlet_blocklist: Set[str]) -> str:
    if not text:
        return ""
    cleaned = text
    # Remove full outlet names/aliases so clustering focuses on event content.
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


def _refine_clusters_for_coherence(
    clusters: Dict[int, List[int]],
    embeddings: np.ndarray,
) -> Dict[int, List[int]]:
    next_label = max(clusters.keys(), default=-1) + 1
    refined: Dict[int, List[int]] = {}
    for label, indices in clusters.items():
        split_groups = _split_cluster_if_needed(indices, embeddings, depth=0)
        for group in split_groups:
            refined[next_label] = group
            next_label += 1
    return refined


def _split_cluster_if_needed(
    indices: List[int],
    embeddings: np.ndarray,
    depth: int,
) -> List[List[int]]:
    if len(indices) <= 2:
        return [indices]
    if depth >= MAX_SPLIT_DEPTH:
        return [indices]

    cluster_vectors = embeddings[indices]
    centroid = np.mean(cluster_vectors, axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-8)
    sims = np.dot(cluster_vectors, centroid)
    mean_sim = float(np.mean(sims))
    too_large = len(indices) > MAX_CLUSTER_SIZE
    low_coherence = mean_sim < MIN_CLUSTER_CENTROID_SIMILARITY
    if not too_large and not low_coherence:
        return [indices]

    splitter = AgglomerativeClustering(
        n_clusters=2,
        metric="cosine",
        linkage="average",
    )
    local_labels = splitter.fit_predict(cluster_vectors)
    left = [indices[i] for i, lab in enumerate(local_labels) if int(lab) == 0]
    right = [indices[i] for i, lab in enumerate(local_labels) if int(lab) == 1]
    if not left or not right:
        return [indices]

    return _split_cluster_if_needed(left, embeddings, depth + 1) + _split_cluster_if_needed(
        right, embeddings, depth + 1
    )


def _split_outlet_dominated_clusters(
    clusters: Dict[int, List[int]],
    articles: List[models.Article],
) -> Dict[int, List[int]]:
    next_label = max(clusters.keys(), default=-1) + 1
    refined: Dict[int, List[int]] = {}
    for _, indices in clusters.items():
        if not indices:
            continue
        counts: Dict[str, int] = {}
        for idx in indices:
            outlet = articles[idx].outlet or ""
            counts[outlet] = counts.get(outlet, 0) + 1
        dominant_outlet, dominant_count = max(counts.items(), key=lambda item: item[1])
        share = dominant_count / len(indices)

        if share <= MAX_DOMINANT_OUTLET_SHARE or len(indices) < 4:
            refined[next_label] = indices
            next_label += 1
            continue

        dominant_idxs = [idx for idx in indices if (articles[idx].outlet or "") == dominant_outlet]
        other_idxs = [idx for idx in indices if (articles[idx].outlet or "") != dominant_outlet]

        # Keep split deterministic and avoid empty groups.
        if dominant_idxs and other_idxs:
            refined[next_label] = dominant_idxs
            next_label += 1
            refined[next_label] = other_idxs
            next_label += 1
        else:
            refined[next_label] = indices
            next_label += 1
    return refined


def _dominant_outlet_share(indices: List[int], articles: List[models.Article]) -> float:
    if not indices:
        return 0.0
    counts: Dict[str, int] = {}
    for idx in indices:
        outlet = articles[idx].outlet or ""
        counts[outlet] = counts.get(outlet, 0) + 1
    return max(counts.values()) / len(indices)


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
