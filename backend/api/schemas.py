from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List, Literal

class ScrapeRequest(BaseModel):
    outlets: Optional[List[str]] = None


class ArticleSummaryResponse(BaseModel):
    id: int
    outlet: str
    date: datetime
    title: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleResponse(ArticleSummaryResponse):
    text: Optional[str] = None
    clean_text: Optional[str] = None


class ArticleOutletCountResponse(BaseModel):
    outlet: str
    total_articles: int


class ScrapeRunLogResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime
    status: str
    error: Optional[str] = None
    log_lines: List[str]
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BiasRunResponse(BaseModel):
    status: str
    message: str
    analysis_type: str = "general"
    processed_articles: int
    topics_processed: int
    profiles_updated: int
    embeddings_saved: int
    embedding_provider: str
    embedding_model: str
    cluster_source: str
    cluster_provider: str = "internal"
    clusters_received: Optional[int] = None
    mapping_stats: Optional[dict] = None


class BiasRunRequest(BaseModel):
    analysis_type: Literal["general", "financial"] = "general"
    embedding_mode: Literal["full", "reuse"] = "full"
    clustering_provider: Literal["internal", "external"] = "internal"


class BiasTopicClusterRequest(BaseModel):
    topic_key: str
    topic_label: Optional[str] = None
    article_ids: List[int]


class BiasRunWithClustersRequest(BaseModel):
    clusters: List[BiasTopicClusterRequest]


class ManualArticleBiasRequest(BaseModel):
    outlet: str
    title: str
    text: str
    url: Optional[str] = None
    date: Optional[datetime] = None


class ManualArticlePeerResponse(BaseModel):
    article_id: int
    outlet: str
    title: str
    url: str
    similarity: float
    sentiment_score: float
    sentiment_label: str


class ArticleBiasScoreResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
    analysis_type: str = "general"
    topic_key: str
    topic_label: Optional[str] = None
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    sentiment_bias: float
    group_sentiment_mean: float
    coverage_majority: bool
    coverage_present: bool
    emphasis_bias: Optional[float] = None
    dominant_outlet: bool = False
    emphasis_length_bias: Optional[float] = None
    emphasis_sentence_bias: Optional[float] = None
    emphasis_entity_bias: Optional[float] = None
    political_side_bias: Optional[float] = None
    government_sentiment: Optional[float] = None
    opposition_sentiment: Optional[float] = None
    government_target_count: int = 0
    opposition_target_count: int = 0
    political_actor_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleBiasEvidenceResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
    analysis_type: str = "general"
    topic_key: str
    topic_label: Optional[str] = None
    target_entity: str
    entity_label: Optional[str] = None
    sentence: str
    sentence_index: int
    is_title: bool
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    negative_prob: float
    neutral_prob: float
    positive_prob: float
    canonical_actor: Optional[str] = None
    political_actor_type: Optional[str] = None
    political_side: Optional[str] = None
    political_side_confidence: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleBiasWithArticleResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
    analysis_type: str = "general"
    title: str
    date: datetime
    url: str
    topic_key: str
    topic_label: Optional[str] = None
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    sentiment_bias: float
    group_sentiment_mean: float
    coverage_majority: bool
    coverage_present: bool
    emphasis_bias: Optional[float] = None
    dominant_outlet: bool = False
    emphasis_length_bias: Optional[float] = None
    emphasis_sentence_bias: Optional[float] = None
    emphasis_entity_bias: Optional[float] = None
    political_side_bias: Optional[float] = None
    government_sentiment: Optional[float] = None
    opposition_sentiment: Optional[float] = None
    government_target_count: int = 0
    opposition_target_count: int = 0
    political_actor_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutletBiasProfileResponse(BaseModel):
    id: int
    outlet: str
    analysis_type: str = "general"
    sentiment_bias_avg: float
    sentiment_score_avg: float
    articles_scored: int
    topics_covered: int
    topics_considered: int
    coverage_missing_majority: int
    coverage_bias_rate: float
    missed_topics: Optional[List[str]] = None
    emphasis_bias_avg: Optional[float] = None
    political_side_bias_avg: Optional[float] = None
    government_sentiment_avg: Optional[float] = None
    opposition_sentiment_avg: Optional[float] = None
    political_actor_count: int = 0
    bsi_score: Optional[float] = None
    source_trust_score: Optional[float] = None
    misinformation_risk_score: Optional[float] = None
    bsi_confidence_low: Optional[float] = None
    bsi_confidence_high: Optional[float] = None
    article_count_per_topic_avg: Optional[float] = None
    coverage_bias_rate_soft: Optional[float] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManualArticleBiasResponse(BaseModel):
    article: ArticleResponse
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    target_pair_count: int
    entity_sentiments: List[dict]
    sentence_evidence: List[dict]
    relative_sentiment_bias: Optional[float] = None
    political_side_bias: Optional[float] = None
    government_sentiment: Optional[float] = None
    opposition_sentiment: Optional[float] = None
    government_target_count: int = 0
    opposition_target_count: int = 0
    political_actor_count: int = 0
    peer_sentiment_mean: Optional[float] = None
    peer_count: int
    peer_outlet_count: int
    topic_key: Optional[str] = None
    topic_label: Optional[str] = None
    topic_similarity: Optional[float] = None
    emphasis_bias: Optional[float] = None
    bias_signal: float
    bias_label: str
    saved_article_bias_score: bool
    outlet_profile: Optional[OutletBiasProfileResponse] = None
    matched_articles: List[ManualArticlePeerResponse]
    notes: List[str]


class OutletCompareRequest(BaseModel):
    outlets: List[str]



class TopicSummaryResponse(BaseModel):
    topic_key: str
    topic_label: Optional[str] = None
    article_count: int


class BiasRunLogResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime
    status: str
    analysis_type: str = "general"
    error: Optional[str] = None
    log_lines: List[str]
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OutletBiasSnapshotResponse(BaseModel):
    id: int
    outlet: str
    analysis_type: str = "general"
    run_id: int
    snapshot_date: datetime
    sentiment_bias_avg: float
    sentiment_score_avg: float
    articles_scored: int
    topics_covered: int
    topics_considered: int
    coverage_missing_majority: int
    coverage_bias_rate: float
    missed_topics: Optional[List[str]] = None
    emphasis_bias_avg: Optional[float] = None
    political_side_bias_avg: Optional[float] = None
    government_sentiment_avg: Optional[float] = None
    opposition_sentiment_avg: Optional[float] = None
    political_actor_count: int = 0
    bsi_score: Optional[float] = None
    source_trust_score: Optional[float] = None
    misinformation_risk_score: Optional[float] = None
    bsi_confidence_low: Optional[float] = None
    bsi_confidence_high: Optional[float] = None
    article_count_per_topic_avg: Optional[float] = None
    coverage_bias_rate_soft: Optional[float] = None
    omission_score: Optional[float] = None
    systematic_omission: Optional[bool] = None
    baseline_used_runs: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class OutletTrendResponse(BaseModel):
    outlet: str
    snapshots: List[OutletBiasSnapshotResponse]


class OutletTopicBSIResponse(BaseModel):
    id: int
    run_id: int
    outlet: str
    analysis_type: str = "general"
    topic_key: str
    topic_label: Optional[str] = None
    sentiment_bias_avg: float
    emphasis_bias_avg: Optional[float] = None
    political_side_bias_avg: Optional[float] = None
    coverage_present: bool
    article_count: int
    bsi_score: float
    label_source: Optional[str] = None
    snapshot_date: datetime

    model_config = ConfigDict(from_attributes=True)


class OutletOmissionResponse(BaseModel):
    outlet: str
    current_coverage_bias_rate: float
    current_bsi_score: Optional[float] = None
    omission_score: Optional[float] = None
    systematic_omission: Optional[bool] = None
    baseline_used_runs: Optional[int] = None
    last_run_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AllProfilesResponse(BaseModel):
    last_run_at: Optional[datetime] = None
    profiles: List[OutletBiasProfileResponse]


class AllTrendsResponse(BaseModel):
    last_run_at: Optional[datetime] = None
    trends: List[OutletTrendResponse]


class AllOmissionsResponse(BaseModel):
    last_run_at: Optional[datetime] = None
    omissions: List[OutletOmissionResponse]


class BiasScoresResponse(BaseModel):
    last_run_at: Optional[datetime] = None
    scores: List[OutletTopicBSIResponse]


class TopicCoverageResponse(BaseModel):
    topic_key: str
    topic_label: Optional[str] = None
    covered_by: List[str]
    missed_by: List[str]


class OmittedTopicsResponse(BaseModel):
    last_run_at: Optional[datetime] = None
    topics: List[TopicCoverageResponse]
