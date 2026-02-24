from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/v1/explainability",
    tags=["explainability"]
)

@router.get("/", response_model=List[schemas.UIExplainDataResponse])
def get_explainability(db: Session = Depends(get_db)):
    """Retrieve all explainability records."""
    records = db.query(models.UIExplainData).all()
    return records
