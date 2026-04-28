import json
import trafilatura

from .utils import GHOST_RESPONSE_MIN_BYTES
from .http_client import GhostResponseError


def extract_with_trafilatura(raw_html: str, url: str = "") -> dict[str, str]:
    """Run trafilatura on raw_html; returns {text, title, date}."""
    if len(raw_html.strip()) < GHOST_RESPONSE_MIN_BYTES:
        raise GhostResponseError(f"Ghost response ({len(raw_html)}b) from {url}")

    result: dict[str, str] = {"text": "", "title": "", "date": ""}
    extracted_json = trafilatura.extract(
        raw_html,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    if extracted_json:
        payload = json.loads(extracted_json)
        result["text"] = payload.get("text") or ""
        result["title"] = payload.get("title") or ""
        result["date"] = payload.get("date") or ""

    if not result["text"]:
        result["text"] = trafilatura.extract(
            raw_html,
            include_comments=False,
            include_tables=False,
        ) or ""

    if not result["text"].strip():
        raise ValueError(f"trafilatura returned empty text for {url}")

    return result
