from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Float, Boolean, UniqueConstraint
from .database import Base

class Article(Base):
    __tablename__ = "Article"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, index=True)
    date = Column(DateTime)
    title = Column(String)
    url = Column(String, unique=True)
    text = Column(Text, nullable=True)
    clean_text = Column(Text, nullable=True)
    sentences = Column(JSON, nullable=True)
    entities = Column(JSON, nullable=True)
    entity_sentiments = Column(JSON, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class ScrapeRunLog(Base):
    __tablename__ = "ScrapeRunLog"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    error = Column(Text, nullable=True)
    log_lines = Column(JSON, nullable=False)
    created_at = Column(DateTime)


class ArticleBiasScore(Base):
    __tablename__ = "ArticleBiasScore"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    outlet = Column(String, nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    topic_key = Column(String, nullable=False, index=True)
    topic_label = Column(String, nullable=True)
    sentiment_label = Column(String, nullable=False)
    sentiment_score = Column(Float, nullable=False)
    sentiment_confidence = Column(Float, nullable=False)
    sentiment_bias = Column(Float, nullable=False)
    group_sentiment_mean = Column(Float, nullable=False)
    coverage_majority = Column(Boolean, nullable=False, default=False)
    coverage_present = Column(Boolean, nullable=False, default=True)
    emphasis_bias = Column(Float, nullable=True)
    dominant_outlet = Column(Boolean, nullable=False, default=False)
    emphasis_length_bias = Column(Float, nullable=True)
    emphasis_sentence_bias = Column(Float, nullable=True)
    emphasis_entity_bias = Column(Float, nullable=True)
    political_side_bias = Column(Float, nullable=True)
    government_sentiment = Column(Float, nullable=True)
    opposition_sentiment = Column(Float, nullable=True)
    government_target_count = Column(Integer, nullable=False, default=0)
    opposition_target_count = Column(Integer, nullable=False, default=0)
    political_actor_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "topic_key",
            "analysis_type",
            name="uq_article_bias_article_topic_analysis",
        ),
    )


class ArticleBiasEvidence(Base):
    __tablename__ = "ArticleBiasEvidence"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    outlet = Column(String, nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    topic_key = Column(String, nullable=False, index=True)
    topic_label = Column(String, nullable=True)
    target_entity = Column(String, nullable=False, index=True)
    entity_label = Column(String, nullable=True)
    sentence = Column(Text, nullable=False)
    sentence_index = Column(Integer, nullable=False)
    is_title = Column(Boolean, nullable=False, default=False)
    sentiment_label = Column(String, nullable=False)
    sentiment_score = Column(Float, nullable=False)
    sentiment_confidence = Column(Float, nullable=False)
    negative_prob = Column(Float, nullable=False)
    neutral_prob = Column(Float, nullable=False)
    positive_prob = Column(Float, nullable=False)
    canonical_actor = Column(String, nullable=True, index=True)
    political_actor_type = Column(String, nullable=True)
    political_side = Column(String, nullable=True, index=True)
    political_side_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False)


class ArticleEmbedding(Base):
    __tablename__ = "ArticleEmbedding"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    outlet = Column(String, nullable=False, index=True)
    embedding_provider = Column(String, nullable=False, index=True)
    embedding_model = Column(String, nullable=False, index=True)
    embedding_dimensions = Column(Integer, nullable=False)
    embedding = Column(JSON, nullable=False)
    source_text_hash = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "embedding_provider",
            "embedding_model",
            name="uq_article_embedding_article_provider_model",
        ),
    )


class OutletBiasProfile(Base):
    __tablename__ = "OutletBiasProfile"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    sentiment_bias_avg = Column(Float, nullable=False)
    sentiment_score_avg = Column(Float, nullable=False)
    articles_scored = Column(Integer, nullable=False)
    topics_covered = Column(Integer, nullable=False)
    topics_considered = Column(Integer, nullable=False)
    coverage_missing_majority = Column(Integer, nullable=False)
    coverage_bias_rate = Column(Float, nullable=False)
    missed_topics = Column(JSON, nullable=True)
    emphasis_bias_avg = Column(Float, nullable=True)
    political_side_bias_avg = Column(Float, nullable=True)
    government_sentiment_avg = Column(Float, nullable=True)
    opposition_sentiment_avg = Column(Float, nullable=True)
    political_actor_count = Column(Integer, nullable=False, default=0)
    bsi_score = Column(Float, nullable=True)
    source_trust_score = Column(Float, nullable=True)
    misinformation_risk_score = Column(Float, nullable=True)
    bsi_confidence_low = Column(Float, nullable=True)
    bsi_confidence_high = Column(Float, nullable=True)
    article_count_per_topic_avg = Column(Float, nullable=True)
    coverage_bias_rate_soft = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("outlet", "analysis_type", name="uq_outlet_bias_profile_outlet_analysis"),
    )


class OutletBiasSnapshot(Base):
    __tablename__ = "OutletBiasSnapshot"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    run_id = Column(Integer, nullable=False, index=True)
    snapshot_date = Column(DateTime, nullable=False, index=True)
    sentiment_bias_avg = Column(Float, nullable=False)
    sentiment_score_avg = Column(Float, nullable=False)
    articles_scored = Column(Integer, nullable=False)
    topics_covered = Column(Integer, nullable=False)
    topics_considered = Column(Integer, nullable=False)
    coverage_missing_majority = Column(Integer, nullable=False)
    coverage_bias_rate = Column(Float, nullable=False)
    missed_topics = Column(JSON, nullable=True)
    emphasis_bias_avg = Column(Float, nullable=True)
    political_side_bias_avg = Column(Float, nullable=True)
    government_sentiment_avg = Column(Float, nullable=True)
    opposition_sentiment_avg = Column(Float, nullable=True)
    political_actor_count = Column(Integer, nullable=False, default=0)
    bsi_score = Column(Float, nullable=True)
    source_trust_score = Column(Float, nullable=True)
    misinformation_risk_score = Column(Float, nullable=True)
    bsi_confidence_low = Column(Float, nullable=True)
    bsi_confidence_high = Column(Float, nullable=True)
    article_count_per_topic_avg = Column(Float, nullable=True)
    coverage_bias_rate_soft = Column(Float, nullable=True)
    omission_score = Column(Float, nullable=True)
    systematic_omission = Column(Boolean, nullable=True)
    baseline_used_runs = Column(Integer, nullable=True)


class OutletTopicBSI(Base):
    __tablename__ = "OutletTopicBSI"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    outlet = Column(String, nullable=False, index=True)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    topic_key = Column(String, nullable=False, index=True)
    topic_label = Column(String, nullable=True)
    sentiment_bias_avg = Column(Float, nullable=False)
    emphasis_bias_avg = Column(Float, nullable=True)
    political_side_bias_avg = Column(Float, nullable=True)
    coverage_present = Column(Boolean, nullable=False, default=True)
    article_count = Column(Integer, nullable=False)
    bsi_score = Column(Float, nullable=False)
    label_source = Column(String(32), nullable=True)
    snapshot_date = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "outlet",
            "topic_key",
            "analysis_type",
            name="uq_outlet_topic_bsi_run_outlet_topic_analysis",
        ),
    )


class BiasRunLog(Base):
    __tablename__ = "BiasRunLog"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    analysis_type = Column(String(32), nullable=False, default="general", index=True)
    error = Column(Text, nullable=True)
    log_lines = Column(JSON, nullable=False)
    created_at = Column(DateTime)
