from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

import numpy as np
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

from .text_utils import _sanitize_topic_label, _strip_outlet_markers

SENTIMENT_CHUNK_SIZE = 256
SENTIMENT_CHUNK_OVERLAP = 32
SENTIMENT_LEAD_WEIGHT = 2.0
SENTIMENT_MODEL = os.getenv("BIAS_SENTIMENT_MODEL", "ProsusAI/finbert")

LOCAL_EMBEDDING_MODELS: Dict[str, str] = {
    "minilm_l6": "all-MiniLM-L6-v2",
    "minilm_l12": "all-MiniLM-L12-v2",
    "mpnet_v2": "all-mpnet-base-v2",
    "multilingual_minilm": "paraphrase-multilingual-MiniLM-L12-v2",
}


def _resolve_local_embedding_model(local_embedding_key: str) -> str:
    key = (local_embedding_key or "minilm_l6").strip().lower()
    if key not in LOCAL_EMBEDDING_MODELS:
        supported = ", ".join(sorted(LOCAL_EMBEDDING_MODELS.keys()))
        raise ValueError(f"Unsupported local embedding key '{local_embedding_key}'. Supported: {supported}")
    return LOCAL_EMBEDDING_MODELS[key]


@dataclass(frozen=True)
class SentimentResult:
    label: str
    confidence: float
    score: float


class BiasModelManager:
    def __init__(self, embedding_model_name: str) -> None:
        self.embedding_model_name = embedding_model_name
        self.sentiment_model_name = SENTIMENT_MODEL
        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        tokenizer = AutoTokenizer.from_pretrained(self.sentiment_model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.sentiment_model_name)
        raw_id2label = getattr(model.config, "id2label", {}) or {}
        self.id2label: Dict[int, str] = {}
        for key, value in raw_id2label.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            self.id2label[idx] = str(value).strip().lower()
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
        """Multi-chunk sliding-window sentiment with position-weighted aggregation.

        Chunk 0 gets SENTIMENT_LEAD_WEIGHT because news front-loads key claims.
        """
        all_chunks: List[str] = []
        article_chunk_spans: List[Tuple[int, int]] = []
        for text in texts:
            chunks = self._tokenize_into_chunks(text)
            start = len(all_chunks)
            all_chunks.extend(chunks)
            article_chunk_spans.append((start, len(all_chunks)))

        if not all_chunks:
            return [SentimentResult(label="neutral", confidence=0.0, score=0.0)] * len(texts)

        try:
            raw_results = self.sentiment_pipeline(
                all_chunks,
                truncation=True,
                max_length=SENTIMENT_CHUNK_SIZE,
                top_k=None,
            )
        except TypeError:
            raw_results = self.sentiment_pipeline(
                all_chunks,
                truncation=True,
                max_length=SENTIMENT_CHUNK_SIZE,
                return_all_scores=True,
            )

        def _parse_predictions(item: Any) -> List[Dict[str, Any]]:
            if isinstance(item, list):
                return [r for r in item if isinstance(r, dict)]
            if isinstance(item, dict):
                return [item]
            return []

        mapped: List[SentimentResult] = []
        for span_start, span_end in article_chunk_spans:
            chunk_preds = [_parse_predictions(raw_results[i]) for i in range(span_start, span_end)]
            n = len(chunk_preds)
            if n == 0 or all(len(p) == 0 for p in chunk_preds):
                mapped.append(SentimentResult(label="neutral", confidence=0.0, score=0.0))
                continue

            weights = [1.0 / ((i + 1) ** 0.5) for i in range(n)]
            weights[0] *= SENTIMENT_LEAD_WEIGHT
            total_weight = sum(weights)

            agg_score = 0.0
            best_label = "neutral"
            best_conf = 0.0

            for preds, w in zip(chunk_preds, weights):
                if not preds:
                    continue
                best_chunk = max(preds, key=lambda r: float(r.get("score", 0.0)))
                lbl = self._canonical_sentiment_label(str(best_chunk.get("label", "neutral")))
                conf = float(best_chunk.get("score", 0.0))
                if conf > best_conf:
                    best_conf = conf
                    best_label = lbl
                agg_score += self._distribution_to_score(preds) * w

            final_score = float(max(-1.0, min(1.0, agg_score / total_weight)))
            mapped.append(SentimentResult(label=best_label, confidence=best_conf, score=final_score))

        return mapped

    def generate_topic_label(
        self,
        titles: List[str],
        outlet_blocklist: Set[str],
        cluster_embeddings: np.ndarray | None = None,
    ) -> str:
        if not titles:
            return "Unknown Topic"

        try:
            cleaned_titles = [_strip_outlet_markers(t or "", outlet_blocklist) for t in titles]
            cleaned_titles = [t for t in cleaned_titles if t]
            if not cleaned_titles:
                return "General News"

            if cluster_embeddings is not None and len(cluster_embeddings) == len(titles):
                central_title = self._find_most_central_article_title(cleaned_titles, cluster_embeddings)
                if central_title:
                    sanitized = _sanitize_topic_label(central_title, outlet_blocklist)
                    if sanitized and len(sanitized.split()) >= 3:
                        return sanitized.title()

            combined_text = " ".join(cleaned_titles)
            keywords = self.kw_model.extract_keywords(
                combined_text,
                keyphrase_ngram_range=(2, 4),
                stop_words="english",
                top_n=6,
            )
            if keywords:
                for keyphrase, _ in keywords:
                    label = _sanitize_topic_label(str(keyphrase), outlet_blocklist)
                    if label:
                        return label.title()

            fallback = _sanitize_topic_label(cleaned_titles[0][:60].strip(), outlet_blocklist)
            return (fallback or "General News").title()
        except Exception:
            fallback_src = titles[0] if titles else ""
            fallback = _sanitize_topic_label(fallback_src[:60].strip(), outlet_blocklist)
            return (fallback or "General News").title()

    def _tokenize_into_chunks(self, text: str) -> List[str]:
        try:
            tokenizer = self.sentiment_pipeline.tokenizer
            token_ids = tokenizer.encode(text, add_special_tokens=False)
            step = SENTIMENT_CHUNK_SIZE - SENTIMENT_CHUNK_OVERLAP
            chunks: List[str] = []
            for start in range(0, max(1, len(token_ids)), step):
                chunk_ids = token_ids[start: start + SENTIMENT_CHUNK_SIZE]
                if not chunk_ids:
                    break
                chunks.append(tokenizer.decode(chunk_ids, skip_special_tokens=True))
                if start + SENTIMENT_CHUNK_SIZE >= len(token_ids):
                    break
            return chunks if chunks else [text[:1000]]
        except Exception:
            return [text[:1000]]

    def _find_most_central_article_title(
        self,
        titles: List[str],
        cluster_embeddings: np.ndarray,
    ) -> str | None:
        n = len(titles)
        if n < 2 or len(cluster_embeddings) != n:
            return titles[0] if titles and len(titles[0]) >= 10 else None

        sim_matrix = np.dot(cluster_embeddings, cluster_embeddings.T)
        mean_sims = (sim_matrix.sum(axis=1) - 1.0) / max(n - 1, 1)
        best_title = titles[int(np.argmax(mean_sims))].strip()

        if len(best_title) < 10:
            return None

        title_tokens = [set(t.lower().split()) for t in titles]
        common = title_tokens[0].intersection(*title_tokens[1:])
        max_len = max((len(ts) for ts in title_tokens), default=1)
        if max_len > 0 and len(common) / max_len > 0.70:
            return None

        return best_title

    def _canonical_sentiment_label(self, raw_label: str) -> str:
        normalized = (raw_label or "").strip().lower()
        match = re.fullmatch(r"label[_\-\s]?(\d+)", normalized)
        if match:
            mapped = self.id2label.get(int(match.group(1)))
            if mapped:
                normalized = mapped
        if "pos" in normalized:
            return "positive"
        if "neg" in normalized:
            return "negative"
        if "neu" in normalized:
            return "neutral"
        return normalized or "neutral"

    def _distribution_to_score(self, predictions: List[Dict[str, Any]]) -> float:
        positive = 0.0
        negative = 0.0
        for row in predictions:
            label = self._canonical_sentiment_label(str(row.get("label", "")))
            value = float(row.get("score", 0.0))
            if label == "positive":
                positive += value
            elif label == "negative":
                negative += value
        return float(max(-1.0, min(1.0, positive - negative)))


_MODEL_MANAGERS: Dict[str, BiasModelManager] = {}


def get_models(local_embedding_key: str = "mpnet_v2") -> BiasModelManager:
    model_name = _resolve_local_embedding_model(local_embedding_key)
    manager = _MODEL_MANAGERS.get(model_name)
    if manager is None:
        manager = BiasModelManager(model_name)
        _MODEL_MANAGERS[model_name] = manager
    return manager
