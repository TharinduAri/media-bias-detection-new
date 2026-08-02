from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

import httpx
import numpy as np
import torch
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer
from transformers import (
    AutoModelForSequenceClassification,
    AutoModelForTokenClassification,
    AutoTokenizer,
    pipeline,
)

from .entity_extraction import (
    EntityPreparationStats,
    merge_article_entities,
    normalize_ner_predictions,
    split_article_sentences,
)
from .target_sentiment import (
    SentimentResult,
    TargetPair,
    aggregate_target_sentiment,
    build_target_pairs,
)
from .text_utils import _sanitize_topic_label, _strip_outlet_markers

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SENTIMENT_MODEL = BACKEND_ROOT / "models" / "deberta-v3-newsmtsc"
SENTIMENT_MODEL = os.getenv("SENTIMENT_MODEL", str(DEFAULT_SENTIMENT_MODEL))
SENTIMENT_BATCH_SIZE = max(1, int(os.getenv("SENTIMENT_BATCH_SIZE", "16")))
SENTIMENT_MAX_LENGTH = max(64, int(os.getenv("SENTIMENT_MAX_LENGTH", "256")))
NER_MODEL = os.getenv("NER_MODEL", "dslim/bert-base-NER")
NER_BATCH_SIZE = max(1, int(os.getenv("NER_BATCH_SIZE", "32")))
NER_SENTENCE_LIMIT = max(1, int(os.getenv("NER_SENTENCE_LIMIT", "48")))
NER_MIN_SCORE = min(max(float(os.getenv("NER_MIN_SCORE", "0.65")), 0.0), 1.0)
NER_STRIDE = max(0, int(os.getenv("NER_STRIDE", "32")))

LOCAL_EMBEDDING_MODEL_KEY = "mpnet_v2"
GEMINI_TOPIC_MODEL = os.getenv("GEMINI_TOPIC_MODEL", "gemini-2.0-flash")


def generate_labels_with_gemini(clusters: List[List[str]]) -> List[str | None]:
    """Send all topic clusters in one Gemini request and return a label per cluster.

    Returns a list of the same length as `clusters`. Each entry is a label string
    or None if Gemini failed for that position.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or not clusters:
        return [None] * len(clusters)

    cluster_blocks = []
    for i, titles in enumerate(clusters):
        lines = "\n".join(f"  - {t}" for t in titles[:10])
        cluster_blocks.append(f"Cluster {i + 1}:\n{lines}")

    prompt = (
        "Label each news cluster below with a concise 4-7 word topic (title case).\n\n"
        + "\n\n".join(cluster_blocks)
        + "\n\nRespond with ONLY a JSON array of strings, one per cluster, same order. "
        "Example for 3 clusters: [\"Sri Lanka Budget Crisis\", \"Cricket World Cup\", \"IMF Debt Relief\"]"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TOPIC_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    try:
        resp = None
        for attempt in range(3):
            with httpx.Client(timeout=90) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                logger.warning("[Gemini labels] 429 rate limit, retrying in %ds (attempt %d/3)...", wait, attempt + 1)
                time.sleep(wait)
                continue
            break

        if resp is None or resp.status_code != 200:
            logger.warning(
                "[Gemini labels] HTTP %s: %s",
                resp.status_code if resp else "no response",
                resp.text[:300] if resp else "",
            )
            return [None] * len(clusters)

        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Extract JSON array robustly — find the first '[' and last ']'
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            logger.warning("[Gemini labels] No JSON array found in response: %s", raw[:300])
            return [None] * len(clusters)

        # Strip trailing commas (common LLM JSON quirk) before parsing
        clean = re.sub(r",\s*([}\]])", r"\1", raw[start : end + 1])
        labels = json.loads(clean)
        if not isinstance(labels, list):
            return [None] * len(clusters)

        result: List[str | None] = []
        for i in range(len(clusters)):
            val = labels[i] if i < len(labels) else None
            if val and str(val).strip():
                result.append(str(val).strip().strip('"').strip("'"))
            else:
                result.append(None)
        return result

    except Exception as exc:
        logger.warning("[Gemini labels] Exception: %s", exc, exc_info=True)
        return [None] * len(clusters)
LOCAL_EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"


def _resolve_local_embedding_model(local_embedding_key: str) -> str:
    return LOCAL_EMBEDDING_MODEL_NAME


class BiasModelManager:
    def __init__(self, embedding_model_name: str) -> None:
        self.embedding_model_name = embedding_model_name
        self.sentiment_model_name = self._resolve_sentiment_model(SENTIMENT_MODEL)
        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        self.sentiment_tokenizer = AutoTokenizer.from_pretrained(self.sentiment_model_name)
        self.sentiment_model = AutoModelForSequenceClassification.from_pretrained(
            self.sentiment_model_name
        )
        raw_id2label = getattr(self.sentiment_model.config, "id2label", {}) or {}
        self.id2label: Dict[int, str] = {}
        for key, value in raw_id2label.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            self.id2label[idx] = str(value).strip().lower()
        canonical_labels = {
            self._canonical_sentiment_label(value)
            for value in self.id2label.values()
        }
        required_labels = {"negative", "neutral", "positive"}
        if not required_labels.issubset(canonical_labels):
            raise ValueError(
                "The sentiment model must be a NewsMTSC three-class checkpoint with "
                "negative, neutral, and positive labels. Run train_newsmtsc.py first."
            )

        requested_device = os.getenv("SENTIMENT_DEVICE", "").strip().lower()
        if requested_device:
            self.sentiment_device = torch.device(requested_device)
        else:
            self.sentiment_device = torch.device(
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        self.sentiment_model.to(self.sentiment_device)
        self.sentiment_model.eval()
        self.ner_model_name = NER_MODEL
        self.ner_tokenizer = AutoTokenizer.from_pretrained(self.ner_model_name)
        self.ner_model = AutoModelForTokenClassification.from_pretrained(
            self.ner_model_name
        )
        self.ner_pipeline = pipeline(
            "ner",
            model=self.ner_model,
            tokenizer=self.ner_tokenizer,
            aggregation_strategy="simple",
            device=self.sentiment_device,
        )
        self.kw_model = KeyBERT(model=self.embedding_model)

    def embed(self, texts: List[str]) -> np.ndarray:
        return np.asarray(self.embedding_model.encode(texts, normalize_embeddings=True))

    def analyze_sentiment(self, articles: List[Any]) -> List[SentimentResult]:
        """Classify sentiment toward named targets, then aggregate per article."""
        pairs = build_target_pairs(articles)
        if not pairs:
            return [
                SentimentResult(label="neutral", confidence=0.0, score=0.0)
                for _ in articles
            ]

        distributions = self._predict_target_pairs(pairs)
        return aggregate_target_sentiment(len(articles), pairs, distributions)

    def prepare_article_targets(
        self,
        articles: List[Any],
    ) -> EntityPreparationStats:
        sentence_updates = 0
        work_items: List[tuple[int, str]] = []
        extracted_by_article: Dict[int, List[List[Dict[str, Any]]]] = {}

        for article_index, article in enumerate(articles):
            sentences = split_article_sentences(article, limit=80)
            stored_sentences = getattr(article, "sentences", None)
            if not isinstance(stored_sentences, list) or not stored_sentences:
                article.sentences = sentences
                if sentences:
                    sentence_updates += 1

            stored_entities = getattr(article, "entities", None)
            if isinstance(stored_entities, list) and stored_entities:
                continue

            candidate_texts: List[str] = []
            title = str(getattr(article, "title", "") or "").strip()
            if title:
                candidate_texts.append(title)
            candidate_texts.extend(sentences[:NER_SENTENCE_LIMIT])
            for text in candidate_texts:
                work_items.append((article_index, text))

        for start in range(0, len(work_items), NER_BATCH_SIZE):
            batch = work_items[start : start + NER_BATCH_SIZE]
            texts = [text for _, text in batch]
            raw_batch = self.ner_pipeline(
                texts,
                batch_size=NER_BATCH_SIZE,
                stride=NER_STRIDE,
            )
            if len(batch) == 1 and raw_batch and isinstance(raw_batch[0], dict):
                raw_batch = [raw_batch]

            for (article_index, text), predictions in zip(batch, raw_batch):
                normalized = normalize_ner_predictions(
                    text,
                    predictions if isinstance(predictions, list) else [],
                    NER_MIN_SCORE,
                )
                extracted_by_article.setdefault(article_index, []).append(normalized)

        entity_updates = 0
        total_entities = 0
        for article_index, groups in extracted_by_article.items():
            article = articles[article_index]
            merged = merge_article_entities(getattr(article, "entities", None), groups)
            article.entities = merged
            if merged:
                entity_updates += 1
                total_entities += len(merged)

        return EntityPreparationStats(
            articles_scanned=len(articles),
            articles_with_sentences_added=sentence_updates,
            articles_with_entities_added=entity_updates,
            sentences_scanned=len(work_items),
            entities_extracted=total_entities,
        )

    def _predict_target_pairs(
        self,
        pairs: List[TargetPair],
    ) -> List[Dict[str, float]]:
        distributions: List[Dict[str, float]] = []
        for start in range(0, len(pairs), SENTIMENT_BATCH_SIZE):
            batch = pairs[start : start + SENTIMENT_BATCH_SIZE]
            encoded = self.sentiment_tokenizer(
                [pair.target for pair in batch],
                [pair.sentence for pair in batch],
                padding=True,
                truncation=True,
                max_length=SENTIMENT_MAX_LENGTH,
                return_tensors="pt",
            )
            encoded = {
                key: value.to(self.sentiment_device)
                for key, value in encoded.items()
            }
            with torch.inference_mode():
                logits = self.sentiment_model(**encoded).logits
                probabilities = torch.softmax(logits, dim=-1).detach().cpu().numpy()

            for row in probabilities:
                distribution = {
                    "negative": 0.0,
                    "neutral": 0.0,
                    "positive": 0.0,
                }
                for label_id, value in enumerate(row):
                    label = self._canonical_sentiment_label(
                        self.id2label.get(label_id, f"label_{label_id}")
                    )
                    if label in distribution:
                        distribution[label] += float(value)
                distributions.append(distribution)
        return distributions

    @staticmethod
    def _resolve_sentiment_model(configured_model: str) -> str:
        candidate = Path(configured_model)
        if candidate.is_absolute():
            if not candidate.exists():
                raise FileNotFoundError(
                    f"Target sentiment model not found at {candidate}. "
                    "Run backend/train_newsmtsc.py to create it."
                )
            return str(candidate)

        local_candidate = BACKEND_ROOT / candidate
        if local_candidate.exists():
            return str(local_candidate)
        if configured_model == "models/deberta-v3-newsmtsc":
            raise FileNotFoundError(
                f"Target sentiment model not found at {local_candidate}. "
                "Run backend/train_newsmtsc.py to create it."
            )
        return configured_model

    def generate_topic_label(
        self,
        titles: List[str],
        outlet_blocklist: Set[str],
        cluster_embeddings: np.ndarray | None = None,
        gemini_label: str | None = None,
    ) -> Tuple[str, str]:
        """Return (topic_label, label_source).

        label_source: "gemini" | "centroid_title" | "keybert" | "first_title" | "fallback"
        """
        if not titles:
            return "Unknown Topic", "fallback"

        try:
            cleaned_titles = [_strip_outlet_markers(t or "", outlet_blocklist) for t in titles]
            cleaned_titles = [t for t in cleaned_titles if t]
            if not cleaned_titles:
                return "General News", "fallback"

            # 1. Use pre-fetched Gemini label if available
            if gemini_label:
                sanitized = _sanitize_topic_label(gemini_label, outlet_blocklist)
                if sanitized and len(sanitized.split()) >= 2:
                    return sanitized.title(), "gemini"

            # 2. Fall back: most central article title
            if cluster_embeddings is not None and len(cluster_embeddings) == len(titles):
                central_title = self._find_most_central_article_title(cleaned_titles, cluster_embeddings)
                if central_title:
                    sanitized = _sanitize_topic_label(central_title, outlet_blocklist)
                    if sanitized and len(sanitized.split()) >= 3:
                        return sanitized.title(), "centroid_title"

            # 3. Fall back: KeyBERT keyword extraction
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
                        return label.title(), "keybert"

            fallback = _sanitize_topic_label(cleaned_titles[0][:60].strip(), outlet_blocklist)
            return (fallback or "General News").title(), "first_title"
        except Exception:
            fallback_src = titles[0] if titles else ""
            fallback = _sanitize_topic_label(fallback_src[:60].strip(), outlet_blocklist)
            return (fallback or "General News").title(), "fallback"

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


def get_models(local_embedding_key: str = LOCAL_EMBEDDING_MODEL_KEY) -> BiasModelManager:
    manager = _MODEL_MANAGERS.get(LOCAL_EMBEDDING_MODEL_NAME)
    if manager is None:
        manager = BiasModelManager(LOCAL_EMBEDDING_MODEL_NAME)
        _MODEL_MANAGERS[LOCAL_EMBEDDING_MODEL_NAME] = manager
    return manager
