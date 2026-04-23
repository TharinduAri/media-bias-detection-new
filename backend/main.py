from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.database import db_manager
from api.routers import system, outlets, articles


@asynccontextmanager
async def lifespan(_: FastAPI):
    db_manager.connect()
    try:
        yield
    finally:
        db_manager.disconnect()

app = FastAPI(
    title="Media Scraper API",
    description="API for scraping outlets and storing raw articles.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration to allow local Streamlit/NextJS to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to frontend domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the modular routers
app.include_router(system.router)
app.include_router(outlets.router)
app.include_router(articles.router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Welcome to the Media Scraper API."}
