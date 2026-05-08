from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.dialects.postgresql import insert as pg_insert

from api import models
from api.database import db_manager


DB_CONNECT_MAX_RETRIES = 5
DB_CONNECT_BACKOFF_BASE_SECONDS = 1.5
STRICT_RECENT_ONLY = True

import os
DB_CONNECT_MAX_RETRIES = int(os.getenv("DB_CONNECT_MAX_RETRIES", "5"))
DB_CONNECT_BACKOFF_BASE_SECONDS = float(os.getenv("DB_CONNECT_BACKOFF_BASE_SECONDS", "1.5"))
STRICT_RECENT_ONLY = os.getenv("STRICT_RECENT_ONLY", "true").strip().lower() == "true"
DAYS_BACK = int(os.getenv("DAYS_BACK", "28"))

FALLBACK_JSONL_PATH = Path(__file__).resolve().parents[3] / "data" / "db_fallback_articles.jsonl"


def _append_articles_to_fallback_jsonl(articles: list[dict[str, str]]) -> None:
    if not articles:
        return
    FALLBACK_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FALLBACK_JSONL_PATH.open("a", encoding="utf-8") as handle:
        for article in articles:
            handle.write(json.dumps(article, ensure_ascii=True) + "\n")
    logging.warning(
        "Database unreachable. Appended %s articles to fallback queue at %s",
        len(articles),
        str(FALLBACK_JSONL_PATH),
    )


def _load_fallback_articles() -> list[dict[str, str]]:
    if not FALLBACK_JSONL_PATH.exists():
        return []
    records: list[dict[str, str]] = []
    with FALLBACK_JSONL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append({k: str(v) if v is not None else "" for k, v in payload.items()})
    return records


def _clear_fallback_articles() -> None:
    if FALLBACK_JSONL_PATH.exists():
        FALLBACK_JSONL_PATH.unlink()


def _write_fallback_articles(records: list[dict[str, str]]) -> None:
    if not records:
        _clear_fallback_articles()
        return
    FALLBACK_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FALLBACK_JSONL_PATH.open("w", encoding="utf-8") as handle:
        for article in records:
            handle.write(json.dumps(article, ensure_ascii=True) + "\n")


def _parse_article_datetime(raw_date: object) -> datetime | None:
    if raw_date is None:
        return None
    text = str(raw_date).strip()
    if not text:
        return None

    iso_candidates = [text]
    if text.endswith("Z"):
        iso_candidates.append(text[:-1] + "+00:00")
    for candidate in iso_candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    known_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%B %d, %Y %I:%M %p",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in known_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def _parse_dt_from_article(article: dict[str, str]) -> datetime:
    raw = article.get("date") or ""
    parsed = _parse_article_datetime(raw)
    if parsed is not None:
        # Store as naive UTC for consistency with the Article model (no tzinfo column).
        return parsed.replace(tzinfo=None)
    return datetime.utcnow()


def _filter_recent_articles(
    records: list[dict[str, str]], days_back: int
) -> tuple[list[dict[str, str]], int, int]:
    if not records:
        return [], 0, 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    kept: list[dict[str, str]] = []
    dropped_old = 0
    dropped_unknown = 0
    for article in records:
        parsed = _parse_article_datetime(article.get("date"))
        if parsed is None:
            if STRICT_RECENT_ONLY:
                dropped_unknown += 1
                continue
        elif parsed < cutoff:
            dropped_old += 1
            continue
        kept.append(article)
    return kept, dropped_old, dropped_unknown


def replay_fallback_articles() -> None:
    pending = _load_fallback_articles()
    if not pending:
        return
    pending, dropped_old, dropped_unknown = _filter_recent_articles(pending, DAYS_BACK)
    if dropped_old:
        logging.info("Fallback replay dropped %d stale records older than %d days", dropped_old, DAYS_BACK)
    if dropped_unknown:
        logging.info("Fallback replay dropped %d records with unknown/unparseable date", dropped_unknown)
    _write_fallback_articles(pending)
    if not pending:
        logging.info("Fallback queue contains no recent articles after strict filtering")
        return

    logging.info("Replaying %s fallback articles from %s", len(pending), str(FALLBACK_JSONL_PATH))
    if save_to_db(pending, allow_fallback=False):
        _clear_fallback_articles()
        logging.info("Fallback replay succeeded; cleared local fallback queue")
    else:
        logging.warning("Fallback replay failed; keeping queued records on disk")


def save_to_db(valid_articles: list[dict[str, Any]], allow_fallback: bool = True) -> bool:
    if not valid_articles:
        logging.warning("No valid articles collected.")
        return True

    valid_articles, dropped_old, dropped_unknown = _filter_recent_articles(valid_articles, DAYS_BACK)
    if dropped_old:
        logging.info("Persistence gate dropped %d stale records older than %d days", dropped_old, DAYS_BACK)
    if dropped_unknown:
        logging.info("Persistence gate dropped %d records with unknown/unparseable date", dropped_unknown)
    if not valid_articles:
        logging.warning("No recent records left after persistence date filter.")
        return True

    now = datetime.utcnow()

    rows: list[dict[str, Any]] = []
    for article in valid_articles:
        dt = _parse_dt_from_article(article)
        rows.append(
            {
                "outlet": article.get("outlet", ""),
                "date": dt,
                "title": article.get("title", article.get("url", "")),
                "url": article.get("url", ""),
                "text": article.get("text", ""),
                "created_at": now,
                "updated_at": now,
            }
        )

    for attempt in range(1, DB_CONNECT_MAX_RETRIES + 1):
        session = db_manager.session_factory()
        try:
            stmt = (
                pg_insert(models.Article)
                .values(rows)
                .on_conflict_do_update(
                    index_elements=["url"],
                    set_={
                        "title": pg_insert(models.Article).excluded.title,
                        "text": pg_insert(models.Article).excluded.text,
                        "updated_at": pg_insert(models.Article).excluded.updated_at,
                    },
                )
            )
            session.execute(stmt)
            session.commit()
            logging.info("Saved %s articles to DB (batch upsert)", len(rows))
            return True

        except Exception as e:
            session.rollback()
            wait_seconds = DB_CONNECT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                "DB save attempt %s/%s failed: %s",
                attempt,
                DB_CONNECT_MAX_RETRIES,
                str(e),
            )
            if attempt < DB_CONNECT_MAX_RETRIES:
                logging.info("Retrying DB save in %.1fs", wait_seconds)
                time.sleep(wait_seconds)
            else:
                logging.error("DB save failed after %s attempts", DB_CONNECT_MAX_RETRIES)
                if allow_fallback:
                    _append_articles_to_fallback_jsonl(valid_articles)
                return False
        finally:
            session.close()

    return False
