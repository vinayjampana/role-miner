"""Company registry endpoints."""
import asyncio
import json
import logging
import sqlite3
import time
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

import config
from roleminer.api.dependencies import active_runs, get_db
from roleminer.api.models import CompanyOut, DiscoverRequest, TriggerResponse
from roleminer.registry.career_finder import discover_companies
from roleminer.registry.db import (
    get_all_companies,
    init_db,
    insert_run,
    insert_run_event,
    update_run,
    update_last_scraped,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["companies"])


def _parse_tech_stack(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(db: sqlite3.Connection = Depends(get_db)):
    rows = get_all_companies(db)
    out: list[CompanyOut] = []
    for r in rows:
        out.append(
            CompanyOut(
                id=r["id"],
                name=r["name"],
                domain=r.get("domain"),
                ats_type=r.get("ats_type"),
                careers_url=r.get("careers_url"),
                ats_slug=r.get("ats_slug"),
                tech_stack=_parse_tech_stack(r.get("tech_stack")),
                location=r.get("location"),
                hq_city=r.get("hq_city"),
                size_category=r.get("size_category"),
                company_type=r.get("company_type"),
                funding_stage=r.get("funding_stage"),
                last_scraped_at=r.get("last_scraped_at"),
                embedding_id=r.get("embedding_id"),
            )
        )
    return sorted(out, key=lambda c: c.name.lower())


@router.post("/companies/{company_id}/scrape", response_model=TriggerResponse)
async def scrape_single_company(
    company_id: int,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not row:
        raise HTTPException(404, "company not found")
    company = dict(row)
    company_name = company.get("name", f"company-{company_id}")

    run_id = insert_run(db, {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "status": "running",
    })
    queue: asyncio.Queue = asyncio.Queue()
    active_runs[run_id] = queue
    asyncio.create_task(_scrape_company_background(run_id, company_id, company_name, queue))
    return {"run_id": run_id}


async def _scrape_company_background(
    run_id: int,
    company_id: int,
    company_name: str,
    queue: asyncio.Queue,
) -> None:
    conn = init_db(config.DB_PATH)
    started = time.time()
    try:
        from roleminer.scrapers.base import make_session
        from main import _scrape_company, _pipeline_post_scrape
        from roleminer.registry.db import (
            get_active_profile_for_user,
            search_profile_row_to_pipeline_dict,
            ensure_default_user_id,
        )

        user_id = ensure_default_user_id(conn)
        _, prow = get_active_profile_for_user(conn, user_id)
        if not prow:
            raise RuntimeError(f"user {user_id} has no active search profile")
        profile = search_profile_row_to_pipeline_dict(prow)

        async def emit(event_type: str, data: dict):
            insert_run_event(conn, run_id, event_type, data, source=company_name)
            await queue.put({"type": event_type, "source": company_name, "data": data})

        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        company = dict(row)

        await emit("scrape_start", {
            "total_sources": 1,
            "companies": [company_name],
        })

        await emit("scraper_start", {
            "company": company_name,
            "ats": company.get("ats_type"),
        })

        async with make_session() as session:
            jobs = await _scrape_company(company, session, profile, conn=conn)

        if jobs:
            update_last_scraped(conn, company_id)

        dur_ms = int((time.time() - started) * 1000)
        await emit("scraper_done", {
            "company": company_name,
            "ats": company.get("ats_type"),
            "jobs_fetched": len(jobs),
            "duration_ms": dur_ms,
            "error": None,
        })

        await emit("scrape_done", {"total_jobs": len(jobs)})

        await _pipeline_post_scrape(conn, run_id, jobs, profile, started, queue)
    except Exception as exc:
        logger.error("Company scrape run %d failed: %s", run_id, exc)
        update_run(conn, run_id, {
            "status": "failed",
            "duration_seconds": time.time() - started,
        })
        insert_run_event(conn, run_id, "error", {
            "step": "scraper",
            "company": company_name,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }, source=company_name)
        await queue.put({"type": "done", "data": {"error": str(exc)}})
        await queue.put(None)
    finally:
        active_runs.pop(run_id, None)
        conn.close()


@router.post("/companies/discover")
async def discover_companies_stream(req: DiscoverRequest, db: sqlite3.Connection = Depends(get_db)):
    async def gen():
        results = await discover_companies(req.names, db)
        for r in results:
            yield {"event": "result", "data": json.dumps(r, default=str)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(gen())
