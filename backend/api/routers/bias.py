from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from src.bias.service import (
    ensure_bias_tables,
    get_models,
    run_bias_analysis,
    run_bias_analysis_with_clusters,
)


def _get_last_run_at(db: Session) -> datetime | None:
    row = db.query(models.BiasRunLog).order_by(models.BiasRunLog.id.desc()).first()
    return row.finished_at if row else None

router = APIRouter(
    prefix="/api/v1/bias",
    tags=["bias"],
)

@router.get("/health")
def bias_health():
    try:
        manager = get_models("mpnet_v2")
        return {
            "status": "ok",
            "default_local_embedding_model": manager.embedding_model_name,
            "sentiment_model": manager.sentiment_model_name,
        }
    except Exception as exc:
        return {
            "status": "error",
            "default_local_embedding_model": None,
            "sentiment_model": None,
            "error": str(exc),
        }


@router.post("/run", response_model=schemas.BiasRunResponse)
def run_bias(
    embedding_provider: Literal["local", "gemini"] = Query("local"),
    local_embedding_key: str = Query(
        "mpnet_v2",
        description="Local model key when embedding_provider=local",
    ),
    db: Session = Depends(get_db),
):
    try:
        return run_bias_analysis(
            db,
            embedding_provider=embedding_provider,
            local_embedding_key=local_embedding_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run-with-clusters", response_model=schemas.BiasRunResponse)
def run_bias_with_clusters(
    payload: schemas.BiasRunWithClustersRequest,
    embedding_provider: Literal["local", "gemini"] = Query("local"),
    local_embedding_key: str = Query(
        "mpnet_v2",
        description="Local model key when embedding_provider=local",
    ),
    db: Session = Depends(get_db),
):
    try:
        return run_bias_analysis_with_clusters(
            db=db,
            clusters=payload.clusters,
            embedding_provider=embedding_provider,
            local_embedding_key=local_embedding_key,
        )
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


@router.get("/topics", response_model=list[schemas.TopicSummaryResponse])
def list_bias_topics(
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    rows = (
        db.query(
            models.ArticleBiasScore.topic_key,
            func.max(models.ArticleBiasScore.topic_label).label("topic_label"),
            func.count(models.ArticleBiasScore.id).label("article_count")
        )
        .group_by(models.ArticleBiasScore.topic_key)
        .order_by(func.count(models.ArticleBiasScore.id).desc())
        .all()
    )
    return [{"topic_key": r[0], "topic_label": r[1], "article_count": r[2]} for r in rows]


@router.get("/articles", response_model=list[schemas.ArticleBiasWithArticleResponse])
def list_article_bias_scores(
    outlet: str | None = Query(None, description="Filter by outlet name"),
    topic_key: str | None = Query(None, description="Filter by topic key"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.ArticleBiasScore, models.Article)
        .join(models.Article, models.Article.id == models.ArticleBiasScore.article_id)
        .order_by(models.ArticleBiasScore.sentiment_bias.desc())
    )
    if outlet:
        q = q.filter(models.ArticleBiasScore.outlet == outlet)
    if topic_key:
        q = q.filter(models.ArticleBiasScore.topic_key == topic_key)

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
                topic_label=score.topic_label,
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



@router.get("/logs", response_model=list[schemas.BiasRunLogResponse])
def list_bias_logs(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    ensure_bias_tables()
    rows = (
        db.query(models.BiasRunLog)
        .order_by(models.BiasRunLog.id.desc())
        .limit(limit)
        .all()
    )
    return rows


@router.delete("/cleanup")
def cleanup_bias_results(db: Session = Depends(get_db)):
    ensure_bias_tables()
    deleted_articles = db.query(models.ArticleBiasScore).delete(synchronize_session=False)
    deleted_embeddings = db.query(models.ArticleEmbedding).delete(synchronize_session=False)
    deleted_profiles = db.query(models.OutletBiasProfile).delete(synchronize_session=False)
    deleted_logs = db.query(models.BiasRunLog).delete(synchronize_session=False)
    db.query(models.OutletBiasSnapshot).delete(synchronize_session=False)
    db.query(models.OutletTopicBSI).delete(synchronize_session=False)
    db.commit()
    return {
        "status": "ok",
        "message": "Bias analysis data cleared.",
        "deleted_article_scores": deleted_articles,
        "deleted_article_embeddings": deleted_embeddings,
        "deleted_outlet_profiles": deleted_profiles,
        "deleted_run_logs": deleted_logs,
    }


# ── Agentic-layer & longitudinal endpoints ────────────────────────────────────

@router.get("/profiles", response_model=schemas.AllProfilesResponse)
def get_all_profiles(db: Session = Depends(get_db)):
    ensure_bias_tables()
    profiles = (
        db.query(models.OutletBiasProfile)
        .order_by(models.OutletBiasProfile.outlet.asc())
        .all()
    )
    return schemas.AllProfilesResponse(
        last_run_at=_get_last_run_at(db),
        profiles=profiles,
    )


@router.get("/outlets/{outlet_name}/trend", response_model=list[schemas.OutletBiasSnapshotResponse])
def get_outlet_trend(
    outlet_name: str,
    days_back: int = Query(90, ge=1, le=730),
    db: Session = Depends(get_db),
):
    ensure_bias_tables()
    since = datetime.utcnow() - timedelta(days=days_back)
    rows = (
        db.query(models.OutletBiasSnapshot)
        .filter(models.OutletBiasSnapshot.outlet == outlet_name)
        .filter(models.OutletBiasSnapshot.snapshot_date >= since)
        .order_by(models.OutletBiasSnapshot.snapshot_date.asc())
        .all()
    )
    return rows


@router.get("/trends", response_model=schemas.AllTrendsResponse)
def get_all_trends(
    days_back: int = Query(90, ge=1, le=730),
    db: Session = Depends(get_db),
):
    ensure_bias_tables()
    since = datetime.utcnow() - timedelta(days=days_back)
    rows = (
        db.query(models.OutletBiasSnapshot)
        .filter(models.OutletBiasSnapshot.snapshot_date >= since)
        .order_by(
            models.OutletBiasSnapshot.outlet.asc(),
            models.OutletBiasSnapshot.snapshot_date.asc(),
        )
        .all()
    )
    outlet_map: dict = defaultdict(list)
    for row in rows:
        outlet_map[row.outlet].append(row)
    trends = [
        schemas.OutletTrendResponse(outlet=outlet, snapshots=snaps)
        for outlet, snaps in outlet_map.items()
    ]
    return schemas.AllTrendsResponse(last_run_at=_get_last_run_at(db), trends=trends)


@router.get("/scores", response_model=schemas.BiasScoresResponse)
def get_bias_scores(
    outlet: str | None = Query(None),
    topic_key: str | None = Query(None),
    run_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    ensure_bias_tables()
    q = db.query(models.OutletTopicBSI)
    if outlet:
        q = q.filter(models.OutletTopicBSI.outlet == outlet)
    if topic_key:
        q = q.filter(models.OutletTopicBSI.topic_key == topic_key)
    if run_id is not None:
        q = q.filter(models.OutletTopicBSI.run_id == run_id)
    rows = q.order_by(models.OutletTopicBSI.bsi_score.desc()).all()
    return schemas.BiasScoresResponse(last_run_at=_get_last_run_at(db), scores=rows)


@router.get("/omissions", response_model=schemas.AllOmissionsResponse)
def get_omissions(db: Session = Depends(get_db)):
    ensure_bias_tables()
    subq = (
        db.query(
            models.OutletBiasSnapshot.outlet,
            func.max(models.OutletBiasSnapshot.id).label("max_id"),
        )
        .group_by(models.OutletBiasSnapshot.outlet)
        .subquery()
    )
    latest_snaps = (
        db.query(models.OutletBiasSnapshot)
        .join(subq, models.OutletBiasSnapshot.id == subq.c.max_id)
        .order_by(models.OutletBiasSnapshot.outlet.asc())
        .all()
    )
    omissions = [
        schemas.OutletOmissionResponse(
            outlet=s.outlet,
            current_coverage_bias_rate=s.coverage_bias_rate,
            current_bsi_score=s.bsi_score,
            omission_score=s.omission_score,
            systematic_omission=s.systematic_omission,
            baseline_used_runs=s.baseline_used_runs,
            last_run_at=s.snapshot_date,
        )
        for s in latest_snaps
    ]
    return schemas.AllOmissionsResponse(last_run_at=_get_last_run_at(db), omissions=omissions)
