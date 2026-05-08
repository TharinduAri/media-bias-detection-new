import os
import sys
import subprocess
import threading
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal, get_db

router = APIRouter(
    prefix="/api/v1/system",
    tags=["system"],
)

STAGES = [
    {"key": "scraper", "label": "Scraping articles"},
]

_state_lock = threading.Lock()
_scrape_log_table_ready = False
_scrape_log_table_lock = threading.Lock()
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


def _ensure_scrape_log_table() -> None:
    global _scrape_log_table_ready
    if _scrape_log_table_ready:
        return

    with _scrape_log_table_lock:
        if _scrape_log_table_ready:
            return

        session = SessionLocal()
        try:
            session.execute(
                text(
                    '''
                    CREATE TABLE IF NOT EXISTS "ScrapeRunLog" (
                        id SERIAL PRIMARY KEY,
                        started_at TIMESTAMP NOT NULL,
                        finished_at TIMESTAMP NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        error TEXT NULL,
                        log_lines JSON NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                    '''
                )
            )
            session.commit()
            _scrape_log_table_ready = True
        finally:
            session.close()


def _persist_scrape_run_log(
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: Optional[str],
    log_lines: List[str],
) -> None:
    _ensure_scrape_log_table()

    session = SessionLocal()
    try:
        log_row = models.ScrapeRunLog(
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            error=error,
            log_lines=log_lines,
            created_at=datetime.utcnow(),
        )
        session.add(log_row)
        session.commit()
    finally:
        session.close()


def _run_scraper(cmd: List[str], backend_dir: str, label: str = "Scraper") -> None:
    """Shared subprocess runner used by both full and per-outlet scrape tasks."""
    started_at = datetime.utcnow()
    run_logs: List[str] = [f"{label} started..."]
    run_status = "done"
    run_error: Optional[str] = None

    _update_state(
        running=True,
        status="running",
        current_stage_index=0,
        logs=list(run_logs),
        started_at=started_at.isoformat(),
        finished_at=None,
        error=None,
    )

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=backend_dir,
        )
        for line in proc.stdout:  # type: ignore
            stripped = line.rstrip()
            if stripped:
                run_logs.append(stripped)
                _append_log(stripped)
        proc.wait()

        if proc.returncode != 0:
            run_status = "error"
            run_error = f"{label} failed with exit code {proc.returncode}"
            run_logs.append(f"{label} failed (exit {proc.returncode})")
            _update_state(running=False, status="error",
                          finished_at=datetime.utcnow().isoformat(), error=run_error)
            _append_log(run_error)
            return

        run_logs.append(f"{label} completed successfully")
        _append_log(f"{label} completed successfully")
        _update_state(running=False, status="done", current_stage_index=1,
                      finished_at=datetime.utcnow().isoformat())
    except Exception as exc:
        run_status = "error"
        run_error = str(exc)
        run_logs.append(f"Error: {str(exc)}")
        _append_log(f"Error: {str(exc)}")
        _update_state(running=False, status="error",
                      finished_at=datetime.utcnow().isoformat(), error=run_error)
    finally:
        finished_at = datetime.utcnow()
        try:
            _persist_scrape_run_log(started_at, finished_at, run_status, run_error, run_logs)
        except Exception:
            pass


def run_scraper_task():
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cmd = [sys.executable, "-m", "src.collection.scraper"]
    _run_scraper(cmd, backend_dir, label="Scraper")


def run_scraper_task_for_outlets(outlet_names: List[str]) -> None:
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cmd = [sys.executable, "-m", "src.collection.scraper", "--outlets"] + outlet_names
    label = f"Scraper ({', '.join(outlet_names)})"
    _run_scraper(cmd, backend_dir, label=label)


@router.get("/pipeline-status")
def get_pipeline_status():
    with _state_lock:
        return dict(_pipeline_state)


@router.get("/scrape-logs", response_model=List[schemas.ScrapeRunLogResponse])
def list_scrape_logs(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _ensure_scrape_log_table()
    rows = (
        db.query(models.ScrapeRunLog)
        .order_by(models.ScrapeRunLog.id.desc())
        .limit(limit)
        .all()
    )
    return rows


@router.get("/scrape-logs/latest", response_model=Optional[schemas.ScrapeRunLogResponse])
def latest_scrape_log(db: Session = Depends(get_db)):
    _ensure_scrape_log_table()
    row = db.query(models.ScrapeRunLog).order_by(models.ScrapeRunLog.id.desc()).first()
    return row


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


@router.post("/scrape")
def scrape_outlets(
    payload: schemas.ScrapeRequest,
    background_tasks: BackgroundTasks,
):
    """Run the scraper for specific outlets (or all if none specified). Does not wipe the DB."""
    with _state_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="Scraper is already running.")

    outlet_names = [n.strip() for n in (payload.outlets or []) if n.strip()]

    if outlet_names:
        background_tasks.add_task(run_scraper_task_for_outlets, outlet_names)
        return {
            "status": "ok",
            "message": f"Scraping {len(outlet_names)} outlet(s) in the background.",
            "outlets": outlet_names,
        }
    else:
        background_tasks.add_task(run_scraper_task)
        return {
            "status": "ok",
            "message": "Scraping all outlets in the background.",
            "outlets": [],
        }
