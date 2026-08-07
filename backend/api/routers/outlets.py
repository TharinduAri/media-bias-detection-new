from fastapi import APIRouter

from src.collection.outlet_catalog import get_outlet_registry_metadata


router = APIRouter(
    prefix="/api/v1/outlets",
    tags=["outlets"],
)


@router.get("/registry")
def get_registry():
    return get_outlet_registry_metadata()
