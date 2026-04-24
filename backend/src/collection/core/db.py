import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DB_CONNECT_MAX_RETRIES = int(os.getenv("DB_CONNECT_MAX_RETRIES", "5"))
DB_CONNECT_BACKOFF_BASE_SECONDS = float(os.getenv("DB_CONNECT_BACKOFF_BASE_SECONDS", "1.5"))

_SCHEMA_HAS_RAW_HTML: bool | None = None
FALLBACK_JSONL_PATH = Path(__file__).resolve().parents[3] / "data" / "db_fallback_articles.jsonl"


def _normalize_outlet_url(url: str) -> str:
    return url.strip().rstrip("/")


def _normalize_database_url_for_neon(database_url: str) -> str:
    if not database_url:
        return database_url

    normalized = database_url
    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if "neon.tech" not in host:
        return normalized

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" not in {k.lower(): v for k, v in query.items()}:
        query["sslmode"] = "require"
        parsed = parsed._replace(query=urlencode(query))
        return urlunparse(parsed)

    return normalized


def _create_prisma_client():
    from prisma import Prisma

    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        os.environ["DATABASE_URL"] = _normalize_database_url_for_neon(database_url)

    return Prisma()


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


def replay_fallback_articles() -> None:
    pending = _load_fallback_articles()
    if not pending:
        return

    logging.info("Replaying %s fallback articles from %s", len(pending), str(FALLBACK_JSONL_PATH))
    if save_to_db(pending, allow_fallback=False):
        _clear_fallback_articles()
        logging.info("Fallback replay succeeded; cleared local fallback queue")
    else:
        logging.warning("Fallback replay failed; keeping queued records on disk")


def load_outlets_from_db() -> list[dict[str, str]]:
    db = _create_prisma_client()
    db.connect()
    try:
        outlets = db.outlet.find_many()
        outlet_configs: list[dict[str, str]] = []

        for outlet in outlets:
            normalized_url = _normalize_outlet_url(outlet.url or "")
            if not normalized_url:
                continue

            outlet_configs.append(
                {
                    "name": outlet.name,
                    "url": normalized_url,
                }
            )

        return outlet_configs
    finally:
        db.disconnect()


def save_to_db(valid_articles: list[dict[str, str]], allow_fallback: bool = True) -> bool:
    global _SCHEMA_HAS_RAW_HTML

    if not valid_articles:
        logging.warning("No valid articles collected.")
        return True

    for attempt in range(1, DB_CONNECT_MAX_RETRIES + 1):
        db = _create_prisma_client()
        try:
            db.connect()

            if _SCHEMA_HAS_RAW_HTML is None:
                try:
                    probe_article = next(
                        (a for a in valid_articles if a.get("raw_html")), None
                    )
                    if probe_article:
                        date_raw = probe_article.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if isinstance(date_raw, datetime):
                            probe_dt = date_raw
                        else:
                            try:
                                probe_dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                try:
                                    probe_dt = datetime.strptime(date_raw, "%Y-%m-%d")
                                except ValueError:
                                    probe_dt = datetime.now()

                        probe_create: dict[str, Any] = {
                            "outlet": probe_article.get("outlet", ""),
                            "date": probe_dt,
                            "title": probe_article.get("title", ""),
                            "url": probe_article.get("url", ""),
                            "text": probe_article.get("text", ""),
                            "raw_html": probe_article["raw_html"],
                        }
                        probe_update: dict[str, Any] = {
                            "text": probe_article.get("text", ""),
                            "title": probe_article.get("title", ""),
                            "raw_html": probe_article["raw_html"],
                        }
                        db.article.upsert(
                            where={"url": probe_article.get("url", "")},
                            data=cast(Any, {"create": probe_create, "update": probe_update}),
                        )
                        _SCHEMA_HAS_RAW_HTML = True
                        logging.debug("Schema probe: raw_html column confirmed.")
                    else:
                        _SCHEMA_HAS_RAW_HTML = True
                except Exception as probe_err:
                    if "raw_html" in str(probe_err):
                        _SCHEMA_HAS_RAW_HTML = False
                        logging.warning(
                            "Schema probe: raw_html column absent — omitting from all writes."
                        )
                    else:
                        raise

            include_raw_html = bool(_SCHEMA_HAS_RAW_HTML)

            with db.batch_() as batcher:
                for article in valid_articles:
                    date_raw = article.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(date_raw, datetime):
                        dt = date_raw
                    else:
                        try:
                            dt = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                dt = datetime.strptime(date_raw, "%Y-%m-%d")
                            except ValueError:
                                dt = datetime.now()

                    base_create: dict[str, Any] = {
                        "outlet": article.get("outlet", ""),
                        "date": dt,
                        "title": article.get("title", article.get("url", "")),
                        "url": article.get("url", ""),
                        "text": article.get("text", ""),
                    }
                    base_update: dict[str, Any] = {
                        "text": article.get("text", ""),
                        "title": article.get("title", article.get("url", "")),
                    }

                    if include_raw_html and article.get("raw_html"):
                        base_create["raw_html"] = article["raw_html"]
                        base_update["raw_html"] = article["raw_html"]

                    batcher.article.upsert(
                        where={"url": article.get("url", "")},
                        data=cast(Any, {"create": base_create, "update": base_update}),
                    )

            logging.info("Saved %s articles to DB (batch transaction)", len(valid_articles))
            return True

        except Exception as e:
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
            try:
                db.disconnect()
            except Exception:
                pass

    return False
