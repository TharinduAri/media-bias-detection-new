from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from .database import Base

class AggregatedSentiment(Base):
    __tablename__ = "AggregatedSentiment"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, index=True)
    year_month = Column(String, index=True)
    entity = Column(String, index=True)
    label = Column(String)
    avg_sentiment = Column(Float)
    total_mentions = Column(Integer)
    article_count = Column(Integer)
    created_at = Column(DateTime)

class AggregatedCoverage(Base):
    __tablename__ = "AggregatedCoverage"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, index=True)
    entity = Column(String, index=True)
    label = Column(String)
    total_mentions = Column(Integer)
    article_count = Column(Integer)
    created_at = Column(DateTime)

class PotentialOmission(Base):
    __tablename__ = "PotentialOmission"

    id = Column(Integer, primary_key=True, index=True)
    entity = Column(String, index=True)
    covered_mostly_by = Column(String)
    max_mentions = Column(Integer)
    omitted_by = Column(String)
    created_at = Column(DateTime)

class UIExplainData(Base):
    __tablename__ = "UIExplainData"

    id = Column(Integer, primary_key=True, index=True)
    outlet = Column(String, index=True)
    year_month = Column(String)
    date = Column(DateTime)
    entity = Column(String, index=True)
    label = Column(String)
    sentiment = Column(Float)
    mention_count = Column(Integer)
    article_url = Column(String)
    example_sentence = Column(String)
    example_sentence_score = Column(Float)
    abs_sentiment = Column(Float)
    created_at = Column(DateTime)

class Outlet(Base):
    __tablename__ = "Outlet"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    url = Column(String)
    rss_feeds = Column(JSON, nullable=True)
    created_at = Column(DateTime)
