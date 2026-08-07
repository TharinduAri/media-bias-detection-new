from __future__ import annotations

from datetime import datetime
from typing import Set
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import models
from api.database import Base
from src.bias.scorer import (
    compute_bsi,
    compute_bsi_confidence_interval,
    compute_emphasis_bias,
    compute_soft_coverage_score,
    insert_snapshots_with_omission,
    replace_article_bias_evidence,
    upsert_article_bias_scores,
)


# ── compute_bsi ───────────────────────────────────────────────────────────────

def test_compute_bsi_all_zeros():
    assert compute_bsi(0.0, 0.0, 0.0) == 0.0


def test_compute_bsi_max_values():
    result = compute_bsi(0.5, 1.0, 1.0)
    assert result == pytest.approx(1.0, abs=1e-5)


def test_compute_bsi_mixed():
    # |0.5|/0.5 = 1.0 → s=1.0; c=0.5; |0.25|=0.25 → e=0.25
    result = compute_bsi(0.5, 0.5, 0.25)
    expected = round(0.4 * 1.0 + 0.4 * 0.5 + 0.2 * 0.25, 6)
    assert result == pytest.approx(expected, abs=1e-6)


def test_compute_bsi_clamped_sentiment():
    # sentiment far above 0.5 should be clamped to 1.0
    result = compute_bsi(2.0, 0.0, 0.0)
    assert result == pytest.approx(0.4, abs=1e-5)


def test_compute_bsi_uses_soft_coverage_when_provided():
    hard = compute_bsi(0.0, 0.8, 0.0)
    soft = compute_bsi(0.0, 0.8, 0.0, coverage_bias_rate_soft=0.2)
    assert soft < hard
    assert soft == pytest.approx(compute_bsi(0.0, 0.2, 0.0), abs=1e-6)


# ── compute_bsi_confidence_interval ──────────────────────────────────────────

def test_bootstrap_ci_in_range():
    scores = [0.1, -0.2, 0.3, 0.0, -0.1, 0.2, -0.05]
    low, high = compute_bsi_confidence_interval(scores, 0.5, scores)
    assert 0.0 <= low <= high <= 1.0


def test_bootstrap_ci_single_article_returns_equal_bounds():
    low, high = compute_bsi_confidence_interval([0.3], 0.5, [0.3])
    assert low == high


def test_bootstrap_ci_empty_list():
    low, high = compute_bsi_confidence_interval([], 0.5, [])
    assert low == high


def test_bootstrap_ci_deterministic():
    scores = [0.1, -0.2, 0.3]
    r1 = compute_bsi_confidence_interval(scores, 0.4, scores, rng_seed=7)
    r2 = compute_bsi_confidence_interval(scores, 0.4, scores, rng_seed=7)
    assert r1 == r2


# ── compute_emphasis_bias ─────────────────────────────────────────────────────

def _make_article(text: str, sentences=None, entities=None):
    a = MagicMock(spec=models.Article)
    a.clean_text = text
    a.text = text
    a.sentences = sentences or []
    a.entities = entities or []
    return a


def test_emphasis_bias_returns_dict_of_dicts():
    articles = [
        _make_article("Short text.", ["Short text."], []),
        _make_article("A much longer article with many words in it. " * 10, ["S1.", "S2.", "S3."], [{"t": "X"}]),
        _make_article("Medium length article here. " * 3, ["S1.", "S2."], []),
    ]
    result = compute_emphasis_bias([0, 1, 2], articles)
    assert set(result.keys()) == {0, 1, 2}
    for v in result.values():
        assert "emphasis_bias" in v
        assert "length_bias" in v
        assert "sentence_bias" in v
        assert "entity_bias" in v
        assert -1.0 <= v["emphasis_bias"] <= 1.0


def test_emphasis_bias_long_article_positive():
    articles = [
        _make_article("x" * 10),
        _make_article("x" * 10),
        _make_article("x" * 1000),  # clearly longest
    ]
    result = compute_emphasis_bias([0, 1, 2], articles)
    assert result[2]["length_bias"] > 0
    assert result[0]["length_bias"] < 0


def test_emphasis_bias_all_equal_lengths():
    articles = [_make_article("same text.") for _ in range(4)]
    result = compute_emphasis_bias([0, 1, 2, 3], articles)
    for v in result.values():
        assert v["length_bias"] == pytest.approx(0.0, abs=1e-6)


def test_emphasis_bias_components_independent():
    # Long text, few sentences, no entities
    articles = [
        _make_article("x" * 1000, sentences=["S1."], entities=[]),
        _make_article("x" * 100, sentences=["S1.", "S2.", "S3.", "S4.", "S5.", "S6.", "S7.", "S8.", "S9.", "S10."], entities=[{"t": "E1"}, {"t": "E2"}, {"t": "E3"}]),
    ]
    result = compute_emphasis_bias([0, 1], articles)
    # Article 0: long text (positive length_bias) but few sentences (negative sentence_bias)
    assert result[0]["length_bias"] > 0
    assert result[0]["sentence_bias"] < 0
    # Article 1: short text (negative length_bias) but many sentences/entities
    assert result[1]["length_bias"] < 0
    assert result[1]["sentence_bias"] > 0


# ── compute_soft_coverage_score ───────────────────────────────────────────────

def test_soft_coverage_full_coverage():
    outlets = ["A", "B", "C"]
    sets = [{"A", "B", "C"}, {"A", "B", "C"}]
    weights = [1.0, 1.0]
    score = compute_soft_coverage_score("A", outlets, sets, weights)
    assert score == pytest.approx(0.0, abs=1e-6)


def test_soft_coverage_zero_coverage():
    outlets = ["A", "B", "C"]
    sets = [{"B", "C"}, {"B", "C"}]  # A never appears
    weights = [1.0, 1.0]
    score = compute_soft_coverage_score("A", outlets, sets, weights)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_soft_coverage_mixed():
    outlets = ["A", "B", "C"]
    sets = [{"A", "B", "C"}, {"B", "C"}, {"A", "B", "C"}]
    weights = [1.0, 1.0, 1.0]
    score_a = compute_soft_coverage_score("A", outlets, sets, weights)
    score_b = compute_soft_coverage_score("B", outlets, sets, weights)
    # A misses one mainstream topic; B misses none
    assert score_a == pytest.approx(1 / 3, abs=1e-6)
    assert score_b == pytest.approx(0.0, abs=1e-6)


def test_soft_coverage_respects_topic_weights_on_same_scale():
    outlets = ["A", "B", "C"]
    sets = [{"B", "C"}, {"A", "B", "C"}]
    weights = [0.75, 0.25]
    assert compute_soft_coverage_score("A", outlets, sets, weights) == pytest.approx(0.75)


def test_soft_coverage_empty_clusters():
    assert compute_soft_coverage_score("A", ["A"], [], []) == 0.0


# ── upsert_article_bias_scores (composite key) ────────────────────────────────

@pytest.fixture
def mem_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_score(article_id: int, topic_key: str, outlet: str = "Test Outlet") -> models.ArticleBiasScore:
    return models.ArticleBiasScore(
        article_id=article_id,
        outlet=outlet,
        topic_key=topic_key,
        topic_label="Test Topic",
        sentiment_label="neutral",
        sentiment_score=0.1,
        sentiment_confidence=0.8,
        sentiment_bias=0.05,
        group_sentiment_mean=0.05,
        coverage_majority=True,
        coverage_present=True,
        emphasis_bias=0.0,
        dominant_outlet=False,
        emphasis_length_bias=0.0,
        emphasis_sentence_bias=0.0,
        emphasis_entity_bias=0.0,
        created_at=datetime.utcnow(),
    )


def test_upsert_article_bias_scores_single_topic(mem_db):
    score = _make_score(article_id=1, topic_key="topic-abc")
    count = upsert_article_bias_scores(mem_db, [score])
    assert count == 1
    rows = mem_db.query(models.ArticleBiasScore).all()
    assert len(rows) == 1


def test_upsert_article_bias_scores_multi_topic(mem_db):
    """Same article_id in two different topics → two rows."""
    s1 = _make_score(article_id=1, topic_key="topic-aaa")
    s2 = _make_score(article_id=1, topic_key="topic-bbb")
    count = upsert_article_bias_scores(mem_db, [s1, s2])
    assert count == 2
    rows = mem_db.query(models.ArticleBiasScore).all()
    assert len(rows) == 2


def test_upsert_article_bias_scores_deduplicates_same_key(mem_db):
    """Duplicate (article_id, topic_key) pairs should be deduped to 1 row."""
    s1 = _make_score(article_id=1, topic_key="topic-aaa")
    s2 = _make_score(article_id=1, topic_key="topic-aaa")
    count = upsert_article_bias_scores(mem_db, [s1, s2])
    assert count == 1


def test_upsert_article_bias_scores_updates_existing(mem_db):
    original = _make_score(article_id=1, topic_key="topic-aaa")
    upsert_article_bias_scores(mem_db, [original])

    updated = _make_score(article_id=1, topic_key="topic-aaa")
    updated.sentiment_bias = 0.99
    upsert_article_bias_scores(mem_db, [updated])

    rows = mem_db.query(models.ArticleBiasScore).all()
    assert len(rows) == 1
    assert rows[0].sentiment_bias == pytest.approx(0.99, abs=1e-5)


def _make_evidence(
    article_id: int,
    topic_key: str,
    target_entity: str = "IMF",
    sentence: str = "The IMF said reforms were delayed.",
) -> models.ArticleBiasEvidence:
    return models.ArticleBiasEvidence(
        article_id=article_id,
        outlet="Test Outlet",
        topic_key=topic_key,
        topic_label="Test Topic",
        target_entity=target_entity,
        entity_label="ORG",
        sentence=sentence,
        sentence_index=1,
        is_title=False,
        sentiment_label="negative",
        sentiment_score=-0.7,
        sentiment_confidence=0.8,
        negative_prob=0.8,
        neutral_prob=0.1,
        positive_prob=0.1,
        created_at=datetime.utcnow(),
    )


def test_replace_article_bias_evidence_replaces_existing_rows(mem_db):
    original = _make_evidence(1, "topic-aaa", target_entity="IMF")
    assert replace_article_bias_evidence(mem_db, [original]) == 1

    updated = _make_evidence(1, "topic-aaa", target_entity="Government")
    assert replace_article_bias_evidence(mem_db, [updated]) == 1

    rows = mem_db.query(models.ArticleBiasEvidence).all()
    assert len(rows) == 1
    assert rows[0].target_entity == "Government"


def test_replace_article_bias_evidence_clears_scored_key_without_new_evidence(mem_db):
    original = _make_evidence(1, "topic-aaa")
    replace_article_bias_evidence(mem_db, [original])

    assert replace_article_bias_evidence(mem_db, [], scored_keys={(1, "topic-aaa")}) == 0
    assert mem_db.query(models.ArticleBiasEvidence).count() == 0


# ── insert_snapshots_with_omission (new outlet fallback) ─────────────────────

def test_omission_new_outlet_uses_cross_mean(mem_db):
    profile = models.OutletBiasProfile(
        outlet="New Outlet",
        sentiment_bias_avg=0.1,
        sentiment_score_avg=0.1,
        articles_scored=5,
        topics_covered=3,
        topics_considered=5,
        coverage_missing_majority=2,
        coverage_bias_rate=0.4,  # 2/5
        missed_topics=[],
        emphasis_bias_avg=0.0,
        bsi_score=0.3,
        bsi_confidence_low=0.2,
        bsi_confidence_high=0.4,
        article_count_per_topic_avg=2.0,
        coverage_bias_rate_soft=None,
        updated_at=datetime.utcnow(),
    )
    now = datetime.utcnow()
    cross_mean = 0.2  # simulates the avg across all outlets

    insert_snapshots_with_omission(mem_db, [profile], run_id=1, now=now,
                                   cross_outlet_coverage_mean=cross_mean)
    mem_db.commit()

    snaps = mem_db.query(models.OutletBiasSnapshot).all()
    assert len(snaps) == 1
    snap = snaps[0]
    # omission_score = 0.4 - 0.2 = 0.2
    assert snap.omission_score == pytest.approx(0.2, abs=1e-5)
    assert snap.systematic_omission is True  # 0.2 > OMISSION_THRESHOLD (0.15)
    assert snap.baseline_used_runs == 0


def test_omission_existing_outlet_uses_history(mem_db):
    # Create prior snapshots with low coverage_bias_rate
    for i in range(3):
        mem_db.add(models.OutletBiasSnapshot(
            outlet="Old Outlet",
            run_id=i,
            snapshot_date=datetime.utcnow(),
            sentiment_bias_avg=0.0,
            sentiment_score_avg=0.0,
            articles_scored=10,
            topics_covered=5,
            topics_considered=5,
            coverage_missing_majority=0,
            coverage_bias_rate=0.1,
            missed_topics=[],
            emphasis_bias_avg=0.0,
            bsi_score=0.1,
        ))
    mem_db.commit()

    profile = models.OutletBiasProfile(
        outlet="Old Outlet",
        sentiment_bias_avg=0.05,
        sentiment_score_avg=0.05,
        articles_scored=10,
        topics_covered=4,
        topics_considered=5,
        coverage_missing_majority=1,
        coverage_bias_rate=0.2,
        missed_topics=[],
        emphasis_bias_avg=0.0,
        bsi_score=0.2,
        bsi_confidence_low=0.1,
        bsi_confidence_high=0.3,
        article_count_per_topic_avg=2.0,
        coverage_bias_rate_soft=None,
        updated_at=datetime.utcnow(),
    )
    now = datetime.utcnow()
    insert_snapshots_with_omission(mem_db, [profile], run_id=99, now=now,
                                   cross_outlet_coverage_mean=0.5)
    mem_db.commit()

    snap = mem_db.query(models.OutletBiasSnapshot).filter_by(run_id=99).first()
    # hist_avg = 0.1; omission = 0.2 - 0.1 = 0.1 (NOT using cross_mean=0.5)
    assert snap.omission_score == pytest.approx(0.1, abs=1e-5)
    assert snap.baseline_used_runs == 3
