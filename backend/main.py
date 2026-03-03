from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import sentiment, coverage, omissions, explainability, system, outlets, articles

app = FastAPI(
    title="Media Bias Analytics API",
    description="Read-only API for aggregated media bias data.",
    version="1.0.0"
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
app.include_router(sentiment.router)
app.include_router(coverage.router)
app.include_router(omissions.router)
app.include_router(explainability.router)
app.include_router(system.router)
app.include_router(outlets.router)
app.include_router(articles.router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Welcome to the Media Bias Analytics API."}
