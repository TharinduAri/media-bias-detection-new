import os
import sys
import logging
import subprocess
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(
    prefix="/api/v1/system",
    tags=["system"]
)

def run_pipeline_task():
    """Background task to run the data collection and processing pipeline."""
    try:
        # Path to run_pipeline.py relative to this router
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        script_path = os.path.join(backend_dir, "run_pipeline.py")
        
        logging.info(f"Starting background pipeline execution: {script_path}")
        # Run using the same python executable as the FastAPI server
        subprocess.run([sys.executable, script_path], check=True)
        logging.info("Background pipeline execution completed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Pipeline execution failed with exit code {e.returncode}")
    except Exception as e:
        logging.error(f"Failed to start pipeline: {str(e)}")

@router.post("/clean-and-rescrape")
def clean_and_rescrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Cleans all data from the database and triggers a background task to rescrape data.
    """
    try:
        # Define tables to clean. Order doesn't strictly matter without FKs.
        tables = [
            "UIExplainData",
            "PotentialOmission",
            "AggregatedCoverage",
            "AggregatedSentiment",
            "Article"
        ]
        
        # We quote the table names in Postgres to ensure correct case.
        for table in tables:
            db.execute(text(f'DELETE FROM "{table}";'))
        
        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"Database wipe failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database clean failed: {str(e)}")

    # Add the pipeline run to background tasks so we can return immediately
    background_tasks.add_task(run_pipeline_task)

    return {
        "status": "ok", 
        "message": "Database cleaned and rescrape pipeline started in the background."
    }
