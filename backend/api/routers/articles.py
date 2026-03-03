from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import distinct

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/articles",
    tags=["articles"]
)


@router.get("/outlets", response_model=List[str])
def get_article_outlets(db: Session = Depends(get_db)):
    """Return list of distinct outlet names that have articles in the DB."""
    rows = db.query(distinct(models.Article.outlet)).order_by(models.Article.outlet.asc()).all()
    return [r[0] for r in rows]


@router.get("/", response_model=List[schemas.ArticleResponse])
def get_articles(
    outlet: Optional[str] = Query(None, description="Filter by outlet name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return raw scraped articles, optionally filtered by outlet."""
    q = db.query(models.Article).order_by(models.Article.date.desc())
    if outlet:
        q = q.filter(models.Article.outlet == outlet)
    return q.offset(offset).limit(limit).all()
