from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/outlets",
    tags=["outlets"]
)

# ---------------------------------------------------------------------------
# Scraper registry metadata (mirrors _OUTLET_REGISTRY in scraper.py)
# ---------------------------------------------------------------------------
_REGISTRY_META = [
    {
        "domain": "adaderana.lk",
        "scraper_class": "AdaDeranaOutlet",
        "discovery": "Sitemap → Wayback CDX",
        "extraction": "trafilatura (follows 301 redirects)",
        "notes": "Beautified URL redirect: news.php?nid=X → canonical slug",
    },
    {
        "domain": "ceylontoday.lk",
        "scraper_class": "CeylonTodayOutlet",
        "discovery": "Sitemap (follows 301) → RSS",
        "extraction": "trafilatura",
        "notes": "Sitemap moved via 301 redirect; httpx follows automatically",
    },
    {
        "domain": "ft.lk",
        "scraper_class": "DailyFTOutlet",
        "discovery": "Paginated /sitemaps/english-{N} (concurrent, auto-stop)",
        "extraction": "trafilatura",
        "notes": "Custom CMS pagination; 300 articles/page; stops on partial page",
    },
    {
        "domain": "economynext.com",
        "scraper_class": "EconomyNextOutlet",
        "discovery": "WordPress sitemap (posts-post shards only) → RSS",
        "extraction": "trafilatura + browser headers + 500-byte ghost guard",
        "notes": "403 on /culture; ghost responses common; browser headers reduce 500 rate",
    },
    {
        "domain": "lbo.lk",
        "scraper_class": "LBOOutlet",
        "discovery": "WordPress REST API → sitemap shards",
        "extraction": "WP REST API JSON (full content, no HTML scraping required)",
        "notes": "API returns full article content; sitemap shards used as fallback only",
    },
    {
        "domain": "english.newsfirst.lk",
        "scraper_class": "NewsfirstOutlet",
        "discovery": "RSS → sitemap.xml → homepage regex link-scrape",
        "extraction": "trafilatura",
        "notes": "JS-rendered SPA — focused_crawler permanently bypassed",
    },
]


@router.get("/registry")
def get_registry():
    """Return scraper registry metadata for all registered specialist outlets."""
    return _REGISTRY_META


@router.get("/", response_model=List[schemas.OutletResponse])
def get_outlets(db: Session = Depends(get_db)):
    records = db.query(models.Outlet).order_by(models.Outlet.name.asc()).all()
    return records


@router.post("/", response_model=schemas.OutletResponse)
def create_outlet(payload: schemas.OutletCreateRequest, db: Session = Depends(get_db)):
    existing = db.query(models.Outlet).filter(models.Outlet.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Outlet with this name already exists")

    outlet = models.Outlet(
        name=payload.name.strip(),
        url=payload.url.strip(),
        rss_feeds=payload.rss_feeds or [],
        created_at=datetime.utcnow(),
    )

    db.add(outlet)
    db.commit()
    db.refresh(outlet)

    return outlet


@router.delete("/{outlet_id}")
def delete_outlet(outlet_id: int, db: Session = Depends(get_db)):
    outlet = db.query(models.Outlet).filter(models.Outlet.id == outlet_id).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")

    db.delete(outlet)
    db.commit()

    return {"status": "ok", "message": "Outlet deleted successfully"}
