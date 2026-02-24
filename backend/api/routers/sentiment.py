from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/sentiment",
    tags=["sentiment"]
)

@router.get("/", response_model=List[schemas.AggregatedSentimentResponse])
def get_sentiment(db: Session = Depends(get_db)):
    """Retrieve all aggregated sentiment records."""
    records = db.query(models.AggregatedSentiment).all()
    return records
