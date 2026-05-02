"""Job listing endpoints."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
import sqlite3

import config
from roleminer.api.dependencies import get_db
from roleminer.api.models import JobOut
from roleminer.registry.db import get_run

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _read_output_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r") as fh:
        return json.load(fh)


def _latest_output_file() -> Path | None:
    out_dir = config.OUTPUT_DIR
    if not out_dir.exists():
        return None
    files = sorted(out_dir.glob("scored_jobs_*.json"))
    return files[-1] if files else None


@router.get("/latest", response_model=list[JobOut])
def latest_jobs():
    path = _latest_output_file()
    if not path:
        return []
    return _read_output_file(path)


@router.get("/run/{run_id}", response_model=list[JobOut])
def jobs_for_run(run_id: int, db: sqlite3.Connection = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    output_file = run.get("output_file")
    if not output_file:
        return []
    return _read_output_file(Path(output_file))
