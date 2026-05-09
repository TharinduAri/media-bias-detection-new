from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api import models
from src.bias.text_utils import (
    CLUSTER_TEXT_SENTENCE_LIMIT,
    CLUSTER_TITLE_REPEAT,
    _build_article_text,
    _sanitize_topic_label,
    _strip_outlet_markers,
)


def _article(title="", sentences=None, clean_text="", entities=None):
    a = MagicMock(spec=models.Article)
    a.title = title
    a.sentences = sentences if sentences is not None else []
    a.clean_text = clean_text
    a.text = clean_text
    a.entities = entities if entities is not None else []
    return a


# ── CLUSTER_TITLE_REPEAT default changed to 1 (Fix 8) ────────────────────────

def test_title_repeat_default_is_one():
    assert CLUSTER_TITLE_REPEAT == 1


def test_sentence_limit_default_is_twelve():
    assert CLUSTER_TEXT_SENTENCE_LIMIT == 12


# ── _build_article_text: title appears exactly once ────────────────────────────

def test_build_article_text_title_not_repeated():
    article = _article(
        title="Test Title",
        sentences=["Sentence one.", "Sentence two."],
        clean_text="Full body text.",
    )
    text = _build_article_text(article, set())
    assert text.count("Test Title") == 1


def test_build_article_text_sentence_limit_respected():
    # Provide 20 sentences; only up to 12 should appear
    sentences = [f"Sentence {i}." for i in range(20)]
    article = _article(title="Title", sentences=sentences, clean_text="")
    text = _build_article_text(article, set())
    # Count how many of the first 12 sentences appear vs the rest
    included = sum(1 for s in sentences[:12] if s in text)
    excluded = sum(1 for s in sentences[13:] if s in text)
    assert included == 12
    assert excluded == 0


def test_build_article_text_includes_title():
    article = _article(title="Breaking News Today")
    text = _build_article_text(article, set())
    assert "Breaking News Today" in text


def test_build_article_text_strips_outlet_name():
    article = _article(
        title="The Daily Mirror reports crime rises",
        sentences=["Daily Mirror says crime is up."],
        clean_text="",
    )
    blocklist = {"daily mirror", "dailymirror"}
    text = _build_article_text(article, blocklist)
    assert "Daily Mirror" not in text
    assert "crime" in text.lower()


# ── _strip_outlet_markers ─────────────────────────────────────────────────────

def test_strip_outlet_markers_removes_name():
    result = _strip_outlet_markers("BBC News reports today", {"bbc news"})
    assert "BBC News" not in result
    assert "reports today" in result


def test_strip_outlet_markers_case_insensitive():
    result = _strip_outlet_markers("bbc news says hello", {"BBC News"})
    assert "bbc news" not in result.lower()


def test_strip_outlet_markers_empty_blocklist():
    text = "Nothing should change here."
    result = _strip_outlet_markers(text, set())
    assert result == text


# ── _sanitize_topic_label ─────────────────────────────────────────────────────

def test_sanitize_removes_years():
    result = _sanitize_topic_label("Sri Lanka Budget 2024 Crisis", set())
    assert "2024" not in result
    assert "Crisis" in result


def test_sanitize_removes_common_words():
    result = _sanitize_topic_label("latest news update today", set())
    assert "news" not in result.lower()
    assert "update" not in result.lower()


def test_sanitize_removes_outlet_names():
    result = _sanitize_topic_label("BBC News budget debate", {"bbc news"})
    assert "BBC" not in result


def test_sanitize_returns_empty_for_short_result():
    # After removing everything, fewer than 2 words remain
    result = _sanitize_topic_label("news 2023", set())
    assert result == ""


def test_sanitize_limits_to_six_words():
    label = "one two three four five six seven eight"
    result = _sanitize_topic_label(label, set())
    assert len(result.split()) <= 6
