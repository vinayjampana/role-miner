"""Run management + trigger endpoints."""
import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

import config
from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import active_runs, get_db
from roleminer.api.models import RunDetail, RunEvent, RunSummary, TriggerResponse
from roleminer.registry.db import (
    get_run,
    get_run_events,
    get_run_history,
    get_search_profile_row,
    init_db,
    insert_run,
    search_profile_row_to_pipeline_dict,
    update_run,
)

router = APIRouter(tags=["runs"])
logger = logging.getLogger(__name__)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    return get_run_history(db, limit=20, user_id=current.id)


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(
    run_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    ruid = run.get("user_id")
    if ruid is not None and int(ruid) != current.id:
        raise HTTPException(404, "run not found")
    events = get_run_events(db, run_id)
    detail = {**run, "events": events}
    return detail


async def _run_in_background(
    run_id: int,
    user_id: int,
    search_profile_id: int,
    queue: asyncio.Queue,
) -> None:
    """Background task wrapper. Imports inside to avoid circular import at module load."""
    from main import run_pipeline

    conn = init_db(config.DB_PATH)
    started = time.time()
    try:
        prow = get_search_profile_row(conn, search_profile_id)
        if not prow:
            raise RuntimeError(f"profile {search_profile_id} not found")
        profile = search_profile_row_to_pipeline_dict(prow)
        logger.info(
            "Run %d: user=%s profile=%s (skills=%d resume_summary_chars=%d)",
            run_id,
            user_id,
            search_profile_id,
            len(profile.get("skills") or []),
            len((profile.get("resume_summary") or "").strip()),
        )
        await run_pipeline(conn, profile, run_id, user_id=user_id, event_queue=queue)
    except Exception as exc:
        run = get_run(conn, run_id)
        if run and run.get("status") == "running":
            logger.error("Run %d: pipeline raised without updating status: %s", run_id, exc)
            update_run(conn, run_id, {"status": "failed", "duration_seconds": time.time() - started})
        await queue.put({"type": "done", "data": {"error": str(exc)}})
        await queue.put(None)
    finally:
        active_runs.pop(run_id, None)
        conn.close()


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_run(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    if not current.active_profile_id:
        raise HTTPException(400, "user has no active search profile")
    spid = int(current.active_profile_id)
    run_id = insert_run(db, {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "status": "running",
        "user_id": current.id,
        "search_profile_id": spid,
    })
    queue: asyncio.Queue = asyncio.Queue()
    active_runs[run_id] = queue
    asyncio.create_task(_run_in_background(run_id, current.id, spid, queue))
    return {"run_id": run_id}
