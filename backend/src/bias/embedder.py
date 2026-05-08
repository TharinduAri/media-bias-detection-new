from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

import httpx
import numpy as np
from sqlalchemy.orm import Session

from api import models
from .models_manager import BiasModelManager, _resolve_local_embedding_model
from .text_utils import _build_article_text

GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
GEMINI_BATCH_SIZE = 32


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
        chunk = texts[start: start + GEMINI_BATCH_SIZE]
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
    candidates = [configured] + discovered + defaults
    deduped: List[str] = []
    for model in candidates:
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
            for model in data.get("models", []):
                name = str(model.get("name", "")).strip()
                methods = set(model.get("supportedGenerationMethods", []) or [])
                if name and methods.intersection(methods_needed):
                    discovered.append(name)
    except Exception:
        return []
    return discovered


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
        vector_list = [float(v) for v in np.asarray(vector, dtype=np.float32).tolist()]
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


def prepare_embeddings(
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
    if texts:
        avg_chars = int(sum(len(t) for t in texts) / len(texts))
        max_chars = max(len(t) for t in texts)
        run_logs.append(f"Embedding input size (chars): avg={avg_chars}, max={max_chars}")
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


def load_analysis_rows(
    db: Session,
    recent_articles: List[models.Article],
    outlet_blocklist: Set[str],
    embedding_provider: str,
    embedding_model: str,
) -> Tuple[List[Dict[str, Any]], np.ndarray]:
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

    analysis_rows: List[Dict[str, Any]] = []
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
