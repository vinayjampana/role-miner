"""SSE streaming endpoint for live run events."""
import asyncio
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from roleminer.api.dependencies import active_runs, get_db
from roleminer.registry.db import ensure_default_user_id, get_run, get_run_events

router = APIRouter(tags=["stream"])


@router.get("/stream/{run_id}")
async def stream_run(
    run_id: int,
    db: sqlite3.Connection = Depends(get_db),
    user_id: int | None = Query(None, description="Must match the run owner (defaults to user 1)"),
):
    run = get_run(db, run_id)
    if run:
        uid = user_id if user_id is not None else ensure_default_user_id(db)
        ruid = run.get("user_id")
        if ruid is not None and int(ruid) != uid:
            raise HTTPException(status_code=403, detail="run belongs to another user")
    queue = active_runs.get(run_id)

    if queue is None:
        # Run is finished — replay stored events then emit done
        async def replay():
            events = get_run_events(db, run_id)
            for ev in events:
                yield {"data": json.dumps({
                    "type": ev["event_type"],
                    "source": ev.get("source", ""),
                    "data": ev.get("data", {}),
                })}
            yield {"data": json.dumps({"type": "done"})}
        return EventSourceResponse(replay())

    async def live():
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"type": "ping"})}
                continue
            if ev is None:
                yield {"data": json.dumps({"type": "done"})}
                break
            yield {"data": json.dumps(ev)}

    return EventSourceResponse(live())
