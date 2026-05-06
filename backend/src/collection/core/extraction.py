import json
import re

from bs4 import BeautifulSoup
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

    if not result["text"]:
        result["text"] = _extract_text_with_html_fallback(raw_html)

    if not result["text"].strip():
        raise ValueError(f"trafilatura returned empty text for {url}")

    result["text"] = _normalize_text(result["text"])
    return result


def _extract_text_with_html_fallback(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    root = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", attrs={"role": "main"})
        or soup.body
    )
    if root is None:
        return ""

    # Remove non-content noise before collecting paragraphs.
    for bad in root.select("script, style, noscript, nav, footer, aside, form, iframe"):
        bad.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) >= 35]
    if paragraphs:
        return _normalize_text("\n".join(paragraphs))

    return _normalize_text(root.get_text(" ", strip=True))


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
