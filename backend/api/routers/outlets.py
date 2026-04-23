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
        rss_feeds=[],
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
