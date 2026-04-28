from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List

class OutletResponse(BaseModel):
    id: int
    name: str
    url: str
    rss_feeds: Optional[List[str]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class OutletCreateRequest(BaseModel):
    name: str
    url: str
    rss_feeds: Optional[List[str]] = None

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


class ArticleBiasScoreResponse(BaseModel):
    id: int
    article_id: int
    outlet: str
    topic_key: str
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    sentiment_bias: float
    group_sentiment_mean: float
    coverage_majority: bool
    coverage_present: bool
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
    sentiment_label: str
    sentiment_score: float
    sentiment_confidence: float
    sentiment_bias: float
    group_sentiment_mean: float
    coverage_majority: bool
    coverage_present: bool
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
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutletCompareRequest(BaseModel):
    outlets: List[str]


class BiasRunLogResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime
    status: str
    error: Optional[str] = None
    log_lines: List[str]
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
