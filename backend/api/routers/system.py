import os
import sys
import time
import logging
import subprocess
import threading
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(
    prefix="/api/v1/system",
    tags=["system"]
)

# ─────────────────────────────────────────────────────────────
#  In-memory pipeline progress state
# ─────────────────────────────────────────────────────────────
STAGES = [
    {"key": "scraper",        "label": "Scraping articles"},
    {"key": "preprocessor",   "label": "Preprocessing text"},
    {"key": "bias_extractor", "label": "Extracting bias signals"},
    {"key": "aggregator",     "label": "Aggregating data"},
    {"key": "explainer",      "label": "Building explainability"},
]

_state_lock = threading.Lock()
_pipeline_state: dict = {
    "running": False,
    "status": "idle",          # "idle" | "running" | "done" | "error"
    "current_stage_index": -1, # 0-based index into STAGES
    "stages": STAGES,
    "logs": [],                # list of log line strings
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def _update_state(**kwargs):
    with _state_lock:
        _pipeline_state.update(kwargs)


def _append_log(line: str):
    with _state_lock:
        _pipeline_state["logs"].append(line)


def _run_stage_tracked(script_path: str, stage_index: int, python_exec: str):
    """Run a single pipeline script, streaming stdout/stderr into the state logs."""
    _update_state(current_stage_index=stage_index)
    stage_label = STAGES[stage_index]["label"]
    _append_log(f"▶ Starting: {stage_label}")

    cmd = [python_exec, script_path]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:  # type: ignore
            stripped = line.rstrip()
            if stripped:
                _append_log(stripped)
        proc.wait()
        if proc.returncode != 0:
            _append_log(f"✗ Stage failed (exit {proc.returncode}): {stage_label}")
            return False
        _append_log(f"✓ Done: {stage_label}")
        return True
    except Exception as e:
        _append_log(f"✗ Error running {stage_label}: {str(e)}")
        return False


def run_pipeline_task():
    """Background task: run all 5 pipeline stages and track progress."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    python_exec = sys.executable

    _update_state(
        running=True,
        status="running",
        current_stage_index=0,
        logs=["Pipeline started…"],
        started_at=datetime.utcnow().isoformat(),
        finished_at=None,
        error=None,
    )

    all_scripts = [
        ("scraper",        "src/collection/scraper.py"),
        ("preprocessor",   "src/processing/preprocessor.py"),
        ("bias_extractor", "src/extraction/bias_extractor.py"),
        ("aggregator",     "src/aggregation/aggregator.py"),
        ("explainer",      "src/explainability/explainer.py"),
    ]

    start = time.time()
    for idx, (key, rel_path) in enumerate(all_scripts):
        script_path = os.path.join(backend_dir, rel_path)
        success = _run_stage_tracked(script_path, idx, python_exec)
        if not success:
            _update_state(
                running=False,
                status="error",
                finished_at=datetime.utcnow().isoformat(),
                error=f"Pipeline stopped at stage: {STAGES[idx]['label']}",
            )
            return

    elapsed = time.time() - start
    _append_log(f"🎉 Pipeline completed in {elapsed:.1f}s")
    _update_state(
        running=False,
        status="done",
        current_stage_index=len(STAGES),  # all done
        finished_at=datetime.utcnow().isoformat(),
    )


# ─────────────────────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/pipeline-status")
def get_pipeline_status():
    """Return the current pipeline execution state (poll this endpoint)."""
    with _state_lock:
        return dict(_pipeline_state)


@router.post("/clean-and-rescrape")
def clean_and_rescrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Clean all data and trigger the full pipeline in the background."""
    with _state_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="Pipeline is already running.")

    try:
        tables = [
            "UIExplainData",
            "PotentialOmission",
            "AggregatedCoverage",
            "AggregatedSentiment",
            "Article"
        ]
        for table in tables:
            db.execute(text(f'DELETE FROM "{table}";'))
        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"Database wipe failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database clean failed: {str(e)}")

    background_tasks.add_task(run_pipeline_task)

    return {
        "status": "ok",
        "message": "Database cleaned and rescrape pipeline started in the background."
    }


@router.post("/clean-db")
def clean_db_only(db: Session = Depends(get_db)):
    """Clean all data from the database without triggering the pipeline."""
    try:
        tables = [
            "UIExplainData",
            "PotentialOmission",
            "AggregatedCoverage",
            "AggregatedSentiment",
            "Article"
        ]
        for table in tables:
            db.execute(text(f'DELETE FROM "{table}";'))
        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"Database wipe failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database clean failed: {str(e)}")

    return {
        "status": "ok",
        "message": "Database cleaned successfully."
    }
