from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional

class AggregatedSentimentResponse(BaseModel):
    id: int
    outlet: str
    year_month: str
    entity: str
    label: str
    avg_sentiment: float
    total_mentions: int
    article_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AggregatedCoverageResponse(BaseModel):
    id: int
    outlet: str
    entity: str
    label: str
    total_mentions: int
    article_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PotentialOmissionResponse(BaseModel):
    id: int
    entity: str
    covered_mostly_by: str
    max_mentions: int
    omitted_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UIExplainDataResponse(BaseModel):
    id: int
    outlet: str
    year_month: str
    date: datetime
    entity: str
    label: str
    sentiment: float
    mention_count: int
    article_url: str
    example_sentence: str
    example_sentence_score: float
    abs_sentiment: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class OutletResponse(BaseModel):
    id: int
    name: str
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class OutletCreateRequest(BaseModel):
    name: str
    url: str

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
