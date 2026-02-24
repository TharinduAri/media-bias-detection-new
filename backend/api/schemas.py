from pydantic import BaseModel
from datetime import datetime
from typing import Optional

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

    class Config:
        orm_mode = True

class AggregatedCoverageResponse(BaseModel):
    id: int
    outlet: str
    entity: str
    label: str
    total_mentions: int
    article_count: int
    created_at: datetime

    class Config:
        orm_mode = True

class PotentialOmissionResponse(BaseModel):
    id: int
    entity: str
    covered_mostly_by: str
    max_mentions: int
    omitted_by: str
    created_at: datetime

    class Config:
        orm_mode = True

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

    class Config:
        orm_mode = True
