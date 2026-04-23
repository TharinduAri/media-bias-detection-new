from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
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

class Outlet(Base):
    __tablename__ = "Outlet"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    url = Column(String)
    rss_feeds = Column(JSON, nullable=True)
    created_at = Column(DateTime)


class ScrapeRunLog(Base):
    __tablename__ = "ScrapeRunLog"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    error = Column(Text, nullable=True)
    log_lines = Column(JSON, nullable=False)
    created_at = Column(DateTime)
