from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from sqlalchemy import distinct, func

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/articles",
    tags=["articles"]
)

SOURCE_ALIASES = {
    "ft": "Daily FT",
    "dft": "Daily FT",
    "economynext": "Economy Next",
    "lbo": "Lanka Business Online",
    "adaderana": "Ada Derana",
    "dailymirror": "Daily Mirror",
    "ceylontoday": "Ceylon Today",
    "newsfirst": "Newsfirst",
}


@router.get("/outlets", response_model=List[str])
def get_article_outlets(db: Session = Depends(get_db)):
    """Return list of distinct outlet names that have articles in the DB."""
    rows = db.query(distinct(models.Article.outlet)).order_by(models.Article.outlet.asc()).all()
    return [r[0] for r in rows]


@router.get("/outlet-counts", response_model=List[schemas.ArticleOutletCountResponse])
def get_article_outlet_counts(db: Session = Depends(get_db)):
    """Return total raw-article count per outlet."""
    rows = (
        db.query(models.Article.outlet, func.count(models.Article.id).label("total_articles"))
        .group_by(models.Article.outlet)
        .order_by(models.Article.outlet.asc())
        .all()
    )
    return [
        {"outlet": outlet, "total_articles": int(total_articles or 0)}
        for outlet, total_articles in rows
    ]


@router.get("/", response_model=List[schemas.ArticleSummaryResponse])
def get_articles(
    outlet: Optional[str] = Query(None, description="Filter by outlet name"),
    source: Optional[str] = Query(None, description="Outlet alias, e.g. ft, economynext, dailymirror"),
    from_date: Optional[date] = Query(None, alias="from", description="Inclusive lower date bound (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, alias="to", description="Inclusive upper date bound (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return scraped articles with optional outlet alias and date-range filters."""
    q = (
        db.query(models.Article)
        .options(
            load_only(
                models.Article.id,
                models.Article.outlet,
                models.Article.date,
                models.Article.title,
                models.Article.url,
                models.Article.created_at,
            )
        )
        .order_by(models.Article.date.desc())
    )

    if source and not outlet:
        normalized = source.strip().lower()
        outlet = SOURCE_ALIASES.get(normalized)
        if outlet is None:
            # Fall back to direct outlet value if a full outlet name is passed via `source`.
            outlet = source.strip()

    if outlet:
        q = q.filter(models.Article.outlet == outlet)

    if from_date is not None:
        q = q.filter(models.Article.date >= datetime.combine(from_date, time.min))

    if to_date is not None:
        q = q.filter(models.Article.date <= datetime.combine(to_date, time.max))

    return q.offset(offset).limit(limit).all()


@router.get("/{article_id}", response_model=schemas.ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    """Return full text for one article when the UI expands it."""
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.delete("/outlet/{outlet_name}")
def delete_outlet_articles(outlet_name: str, db: Session = Depends(get_db)):
    """Delete all articles for a specific outlet."""
    deleted = (
        db.query(models.Article)
        .filter(models.Article.outlet == outlet_name)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"status": "ok", "message": f"Deleted {deleted} articles for {outlet_name}.", "deleted": deleted}


@router.delete("/{article_id}")
def delete_article(article_id: int, db: Session = Depends(get_db)):
    """Delete a single article by ID."""
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    db.delete(article)
    db.commit()

    return {"status": "ok", "message": "Article deleted successfully"}
