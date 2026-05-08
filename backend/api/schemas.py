from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List

class ScrapeRequest(BaseModel):
    outlets: Optional[List[str]] = None


class ArticleResponse(BaseModel):
    id: int
    outlet: str
    date: datetime
    title: str
    url: str
    text: Optional[str] = None
    clean_text: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    processed_articles: int
    topics_processed: int
    profiles_updated: int
    embeddings_saved: int
    embedding_provider: str
    embedding_model: str
    cluster_source: str
    clusters_received: Optional[int] = None


class BiasTopicClusterRequest(BaseModel):
    topic_key: str
    topic_label: Optional[str] = None
    article_ids: List[int]


class BiasRunWithClustersRequest(BaseModel):
    clusters: List[BiasTopicClusterRequest]


class ArticleBiasScoreResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleBiasWithArticleResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutletBiasProfileResponse(BaseModel):
    id: int
    outlet: str
    sentiment_bias_avg: float
    sentiment_score_avg: float
    articles_scored: int
    topics_covered: int
    topics_considered: int
    coverage_missing_majority: int
    coverage_bias_rate: float
    missed_topics: Optional[List[str]] = None
    emphasis_bias_avg: Optional[float] = None
    bsi_score: Optional[float] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    error: Optional[str] = None
    log_lines: List[str]
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OutletBiasSnapshotResponse(BaseModel):
    id: int
    outlet: str
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
    bsi_score: Optional[float] = None
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
    topic_key: str
    topic_label: Optional[str] = None
    sentiment_bias_avg: float
    emphasis_bias_avg: Optional[float] = None
    coverage_present: bool
    article_count: int
    bsi_score: float
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
