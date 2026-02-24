from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/coverage",
    tags=["coverage"]
)

@router.get("/", response_model=List[schemas.AggregatedCoverageResponse])
def get_coverage(db: Session = Depends(get_db)):
    """Retrieve all aggregated coverage records."""
    records = db.query(models.AggregatedCoverage).all()
    return records
