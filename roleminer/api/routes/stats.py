"""Aggregate stats endpoint."""
import json
import sqlite3
from collections import Counter

from fastapi import APIRouter, Depends

from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import get_db
from roleminer.api.models import StatsOut

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
def stats(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    cur = db.execute(
        """SELECT COUNT(*) AS n, COALESCE(SUM(jobs_scored),0) AS js, COALESCE(SUM(tokens_used),0) AS tk, COALESCE(SUM(cost_usd),0) AS cost
        FROM runs WHERE user_id = ?""",
        (current.id,),
    )
    row = cur.fetchone()

    sources: Counter = Counter()
    cur = db.execute(
        """SELECT e.source, e.data FROM run_events e
        INNER JOIN runs r ON r.id = e.run_id
        WHERE e.event_type = 'scraper_done' AND r.user_id = ?""",
        (current.id,),
    )
    for r in cur.fetchall():
        try:
            data = json.loads(r["data"])
            n = int(data.get("jobs_fetched", 0))
        except Exception:
            n = 0
        sources[r["source"] or "unknown"] += n

    return {
        "total_runs": row["n"] or 0,
        "total_jobs_scored": row["js"] or 0,
        "total_tokens": row["tk"] or 0,
        "total_cost_usd": float(row["cost"] or 0.0),
        "sources_hit": dict(sources),
    }
