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
from roleminer.api.models import CompanyOut, CompanyPatch, DiscoverRequest, TriggerResponse
from roleminer.registry.career_finder import discover_companies
from roleminer.registry.db import (
    get_all_companies,
    init_db,
    insert_run,
    insert_run_event,
    update_run,
    update_last_scraped,
    update_company_fields,
    upsert_company,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["companies"])

# Must match branches in main._scrape_company
ALLOWED_ATS_TYPES = frozenset({
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "cutshort",
    "custom",
    "custom_api",
})


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
    out = [_row_to_company_out(r) for r in rows]
    return sorted(out, key=lambda c: c.name.lower())


def _row_to_company_out(row: sqlite3.Row | dict) -> CompanyOut:
    r = dict(row)
    strategy = r.get("scrape_strategy")
    if isinstance(strategy, str) and strategy:
        try:
            import json as _json
            strategy = _json.loads(strategy)
        except (Exception):
            strategy = None
    return CompanyOut(
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
        scrape_strategy=strategy,
        strategy_status=r.get("strategy_status", "active"),
    )


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def patch_company(
    company_id: int,
    body: CompanyPatch,
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not row:
        raise HTTPException(404, "company not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "provide careers_url and/or ats_type")
    updates: dict = {}
    if "careers_url" in data:
        raw = (data["careers_url"] or "").strip()
        if raw and not (raw.startswith("http://") or raw.startswith("https://")):
            raise HTTPException(
                422,
                "careers_url must start with http:// or https://, or be empty to clear",
            )
        updates["careers_url"] = raw or None
    if "ats_type" in data:
        raw_ats = (data["ats_type"] or "").strip().lower()
        if not raw_ats:
            updates["ats_type"] = None
        elif raw_ats not in ALLOWED_ATS_TYPES:
            raise HTTPException(
                422,
                "ats_type must be empty to clear, or one of: "
                + ", ".join(sorted(ALLOWED_ATS_TYPES)),
            )
        else:
            updates["ats_type"] = raw_ats
    update_company_fields(db, company_id, updates)
    row2 = db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not row2:
        raise HTTPException(404, "company not found")
    return _row_to_company_out(row2)


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

            company_id = r.get("company_id")
            ats_type = r.get("ats_type")
            careers_url = r.get("careers_url")
            if not company_id or not careers_url:
                continue
            if ats_type not in ("custom", "custom_api", None, ""):
                continue

            try:
                from roleminer.registry.network_sniffer import sniff_career_page
                from roleminer.registry.strategy_builder import generate_scrape_strategy

                sniffer_data = await sniff_career_page(careers_url)
                strategy = await generate_scrape_strategy(r.get("name", ""), sniffer_data)
                if strategy:
                    upsert_company(db, {
                        "name": r.get("name", ""),
                        "scrape_strategy": strategy,
                        "strategy_status": "active",
                    })
                    yield {
                        "event": "strategy",
                        "data": json.dumps({
                            "company": r.get("name"),
                            "strategy_type": strategy.get("strategy_type"),
                            "status": "active",
                        }),
                    }
                else:
                    yield {
                        "event": "strategy",
                        "data": json.dumps({
                            "company": r.get("name"),
                            "strategy_type": None,
                            "status": "failed",
                        }),
                    }
            except Exception as exc:
                logger.warning(
                    "[discover] strategy generation failed for %r: %s",
                    r.get("name"), exc,
                )

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(gen())
