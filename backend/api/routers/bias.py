from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from src.bias.service import get_models, run_bias_analysis

router = APIRouter(
    prefix="/api/v1/bias",
    tags=["bias"],
)

_MODEL_MANAGER = get_models()


@router.get("/health")
def bias_health():
    return {
        "status": "ok",
        "embedding_model": _MODEL_MANAGER.embedding_model_name,
        "sentiment_model": _MODEL_MANAGER.sentiment_model_name,
    }


@router.post("/run", response_model=schemas.BiasRunResponse)
def run_bias(db: Session = Depends(get_db)):
    try:
        return run_bias_analysis(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/outlets/{outlet_name}", response_model=schemas.OutletBiasProfileResponse)
def get_outlet_profile(outlet_name: str, db: Session = Depends(get_db)):
    profile = (
        db.query(models.OutletBiasProfile)
        .filter(models.OutletBiasProfile.outlet == outlet_name)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Outlet profile not found")
    return profile


@router.post("/compare", response_model=list[schemas.OutletBiasProfileResponse])
def compare_outlets(payload: schemas.OutletCompareRequest, db: Session = Depends(get_db)):
    if not payload.outlets:
        raise HTTPException(status_code=400, detail="No outlets provided")
    profiles = (
        db.query(models.OutletBiasProfile)
        .filter(models.OutletBiasProfile.outlet.in_(payload.outlets))
        .order_by(models.OutletBiasProfile.outlet.asc())
        .all()
    )
    return profiles


@router.get("/articles/{article_id}", response_model=schemas.ArticleBiasScoreResponse)
def get_article_bias(article_id: int, db: Session = Depends(get_db)):
    score = (
        db.query(models.ArticleBiasScore)
        .filter(models.ArticleBiasScore.article_id == article_id)
        .first()
    )
    if not score:
        raise HTTPException(status_code=404, detail="Bias score not found for article")
    return score


@router.get("/articles", response_model=list[schemas.ArticleBiasWithArticleResponse])
def list_article_bias_scores(
    outlet: str | None = Query(None, description="Filter by outlet name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.ArticleBiasScore, models.Article)
        .join(models.Article, models.Article.id == models.ArticleBiasScore.article_id)
        .order_by(models.ArticleBiasScore.created_at.desc())
    )
    if outlet:
        q = q.filter(models.ArticleBiasScore.outlet == outlet)

    rows = q.offset(offset).limit(limit).all()
    results: list[schemas.ArticleBiasWithArticleResponse] = []
    for score, article in rows:
        results.append(
            schemas.ArticleBiasWithArticleResponse(
                id=score.id,
                article_id=score.article_id,
                outlet=score.outlet,
                title=article.title,
                date=article.date,
                url=article.url,
                topic_key=score.topic_key,
                sentiment_label=score.sentiment_label,
                sentiment_score=score.sentiment_score,
                sentiment_confidence=score.sentiment_confidence,
                sentiment_bias=score.sentiment_bias,
                group_sentiment_mean=score.group_sentiment_mean,
                coverage_majority=score.coverage_majority,
                coverage_present=score.coverage_present,
                created_at=score.created_at,
            )
        )
    return results
