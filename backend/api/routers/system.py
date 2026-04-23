import os
import sys
import subprocess
import threading
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(
    prefix="/api/v1/system",
    tags=["system"],
)

STAGES = [
    {"key": "scraper", "label": "Scraping articles"},
]

_state_lock = threading.Lock()
_pipeline_state: dict = {
    "running": False,
    "status": "idle",  # "idle" | "running" | "done" | "error"
    "current_stage_index": -1,
    "stages": STAGES,
    "logs": [],
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


def run_scraper_task():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    script_path = os.path.join(backend_dir, "src", "collection", "scraper.py")

    _update_state(
        running=True,
        status="running",
        current_stage_index=0,
        logs=["Scraper started..."],
        started_at=datetime.utcnow().isoformat(),
        finished_at=None,
        error=None,
    )

    cmd = [sys.executable, script_path]
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
            _update_state(
                running=False,
                status="error",
                finished_at=datetime.utcnow().isoformat(),
                error=f"Scraper failed with exit code {proc.returncode}",
            )
            _append_log(f"Scraper failed (exit {proc.returncode})")
            return

        _append_log("Scraper completed successfully")
        _update_state(
            running=False,
            status="done",
            current_stage_index=1,
            finished_at=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        _append_log(f"Error running scraper: {str(exc)}")
        _update_state(
            running=False,
            status="error",
            finished_at=datetime.utcnow().isoformat(),
            error=str(exc),
        )


@router.get("/pipeline-status")
def get_pipeline_status():
    with _state_lock:
        return dict(_pipeline_state)


@router.post("/clean-and-rescrape")
def clean_and_rescrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    with _state_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="Scraper is already running.")

    try:
        db.execute(text('DELETE FROM "Article";'))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Article cleanup failed: {str(exc)}")

    background_tasks.add_task(run_scraper_task)
    return {
        "status": "ok",
        "message": "Article table cleaned and scraper started in the background.",
    }


@router.post("/clean-db")
def clean_db_only(db: Session = Depends(get_db)):
    try:
        db.execute(text('DELETE FROM "Article";'))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Article cleanup failed: {str(exc)}")

    return {
        "status": "ok",
        "message": "Article table cleaned successfully.",
    }
