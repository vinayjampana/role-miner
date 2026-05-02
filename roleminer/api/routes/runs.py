"""Run management + trigger endpoints."""
import asyncio
import sqlite3
from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import config
from roleminer.api.dependencies import active_runs, get_db
from roleminer.api.models import RunDetail, RunEvent, RunSummary, TriggerResponse
from roleminer.registry.db import (
    get_run,
    get_run_events,
    get_run_history,
    init_db,
    insert_run,
)

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: sqlite3.Connection = Depends(get_db)):
    return get_run_history(db, limit=20)


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: int, db: sqlite3.Connection = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    events = get_run_events(db, run_id)
    detail = {**run, "events": events}
    return detail


async def _run_in_background(run_id: int, queue: asyncio.Queue) -> None:
    """Background task wrapper. Imports inside to avoid circular import at module load."""
    from main import _load_profile, run_pipeline

    conn = init_db(config.DB_PATH)
    try:
        profile = _load_profile()
        await run_pipeline(conn, profile, run_id, event_queue=queue)
    except Exception:
        pass
    finally:
        active_runs.pop(run_id, None)
        conn.close()


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_run(db: sqlite3.Connection = Depends(get_db)):
    run_id = insert_run(db, {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "status": "running",
    })
    queue: asyncio.Queue = asyncio.Queue()
    active_runs[run_id] = queue
    asyncio.create_task(_run_in_background(run_id, queue))
    return {"run_id": run_id}
