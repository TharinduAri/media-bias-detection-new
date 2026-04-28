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
