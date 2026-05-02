#!/usr/bin/env python3
"""
RoleMiner CLI

Usage:
  python main.py bootstrap   # seed company registry
  python main.py run         # scrape → filter → score → output JSON
  python main.py serve       # run FastAPI server
"""
import asyncio
import json
import logging
import sqlite3
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

import config
from roleminer.registry.db import (
    init_db,
    insert_company,
    get_all_companies,
    insert_run,
    insert_run_event,
    update_run,
    update_last_scraped,
    SEED_COMPANIES,
)
from roleminer.scrapers.base import Job, dedup_by_url, make_session
from roleminer.scrapers import greenhouse, lever, ashby, cutshort, workday
from roleminer.pipeline.classifier import classify_company
from roleminer.pipeline.filter import (
    filter_jobs, detect_work_mode, days_since,
    detect_esop, detect_notice_compatible, _normalize_location,
)
from roleminer.pipeline.role_filter import filter_by_role
from roleminer.pipeline.ranker import rank_jobs
from roleminer.pipeline.scorer import score_jobs, _build_user_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("roleminer.main")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def bootstrap() -> None:
    """Seed company registry with known Indian product companies."""
    logger.info("Bootstrapping company registry …")
    conn = init_db(config.DB_PATH)

    existing = {c["name"].lower() for c in get_all_companies(conn)}
    inserted = 0

    for company in SEED_COMPANIES:
        if company["name"].lower() in existing:
            logger.info("  skip (exists): %s", company["name"])
            continue
        row_id = insert_company(conn, company)
        logger.info("  inserted [%d]: %s (%s / %s)", row_id, company["name"], company.get("ats_type"), company.get("ats_slug"))
        inserted += 1

    conn.close()
    logger.info("Bootstrap complete. Inserted %d companies (%d already existed).", inserted, len(existing))


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _load_profile() -> dict:
    with open(config.SEARCH_PROFILE, "r") as fh:
        return yaml.safe_load(fh)


async def _scrape_company(company: dict, session, profile: dict) -> list[Job]:
    """Scrape one company, returning jobs. Errors are caught and logged."""
    ats_type = company.get("ats_type", "")
    slug = company.get("ats_slug", "")
    name = company.get("name", "")
    careers_url = company.get("careers_url", "")

    if not slug and ats_type not in ("workday", "cutshort"):
        logger.warning("Company '%s' has no ats_slug — skipping", name)
        return []

    try:
        if ats_type == "greenhouse":
            return await greenhouse.scrape(slug, session, company_name=name)
        elif ats_type == "lever":
            return await lever.scrape(slug, session, company_name=name)
        elif ats_type == "ashby":
            return await ashby.scrape(slug, session, company_name=name)
        elif ats_type == "workday":
            return await workday.scrape(careers_url, session, company_name=name)
        elif ats_type == "cutshort":
            skills = profile.get("skills", [])
            locations = profile.get("locations", [])
            return await cutshort.scrape(skills, locations, session)
        else:
            logger.warning("Unknown ats_type '%s' for %s — skipping", ats_type, name)
            return []
    except Exception as exc:
        logger.error("Error scraping %s (%s/%s): %s", name, ats_type, slug, exc)
        return []


async def _emit(
    conn: sqlite3.Connection,
    run_id: int,
    event_type: str,
    data: dict,
    source: str = "",
    queue: Optional[asyncio.Queue] = None,
) -> None:
    insert_run_event(conn, run_id, event_type, data, source=source)
    if queue is not None:
        await queue.put({"type": event_type, "source": source, "data": data})


# ---------------------------------------------------------------------------
# run_pipeline — callable from CLI or FastAPI
# ---------------------------------------------------------------------------

async def run_pipeline(
    conn: sqlite3.Connection,
    profile: dict,
    run_id: int,
    event_queue: Optional[asyncio.Queue] = None,
) -> dict:
    """Full pipeline. Logs structured events to DB (and queue if provided)."""
    started = time.time()
    resume_summary = profile.get("resume_summary", "")
    companies = get_all_companies(conn)

    all_jobs: list[Job] = []

    try:
        async with make_session(proxy_url=config.PROXY_URL) as session:
            # Cutshort (profile-level)
            t0 = time.time()
            try:
                cs_jobs = await cutshort.scrape(
                    skills=profile.get("skills", []),
                    locations=profile.get("locations", []),
                    session=session,
                )
            except Exception as exc:
                logger.error("Cutshort failed: %s", exc)
                cs_jobs = []
                await _emit(conn, run_id, "error", {
                    "step": "scraper", "company": "Cutshort",
                    "error": str(exc), "traceback": traceback.format_exc(),
                }, source="Cutshort", queue=event_queue)
            all_jobs.extend(cs_jobs)
            await _emit(conn, run_id, "scraper_done", {
                "company": "Cutshort", "ats": "cutshort",
                "jobs_fetched": len(cs_jobs),
                "duration_ms": int((time.time() - t0) * 1000),
                "error": None,
            }, source="Cutshort", queue=event_queue)

            for company in companies:
                t0 = time.time()
                err = None
                try:
                    jobs = await _scrape_company(company, session, profile)
                except Exception as exc:
                    jobs = []
                    err = str(exc)
                    await _emit(conn, run_id, "error", {
                        "step": "scraper", "company": company.get("name"),
                        "error": err, "traceback": traceback.format_exc(),
                    }, source=company.get("name", ""), queue=event_queue)
                all_jobs.extend(jobs)
                if jobs and company.get("id"):
                    update_last_scraped(conn, company["id"])
                await _emit(conn, run_id, "scraper_done", {
                    "company": company.get("name"),
                    "ats": company.get("ats_type"),
                    "jobs_fetched": len(jobs),
                    "duration_ms": int((time.time() - t0) * 1000),
                    "error": err,
                }, source=company.get("name", ""), queue=event_queue)

        total_raw = len(all_jobs)

        # Dedup
        all_jobs = dedup_by_url(all_jobs)

        # Classify + work_mode
        for job in all_jobs:
            if not job.company_type:
                job.company_type = classify_company(job.company, job.jd_text)
            if not job.work_mode or job.work_mode == "onsite":
                job.work_mode = detect_work_mode(job.title, job.jd_text, job.location)

        # Filter — track drop reasons
        filter_in = len(all_jobs)
        dropped = Counter()
        sample_dropped: list[dict] = []
        passed: list[Job] = []

        salary_min = profile.get("salary_min_lpa", 0)
        profile_locations = [loc.lower() for loc in profile.get("locations", [])]
        profile_work_modes = [m.lower() for m in profile.get("work_mode", [])]
        profile_company_types = [ct.lower() for ct in profile.get("company_type", [])]
        exclude_companies = [c.lower() for c in profile.get("exclude_companies", [])]
        notice_days = profile.get("notice_days", 0)

        for job in all_jobs:
            job.has_esop = detect_esop(job.jd_text)
            job.notice_compatible = detect_notice_compatible(job.jd_text, notice_days)

            age = days_since(job.date_posted)
            if age > 30:
                dropped["stale"] += 1
                if len(sample_dropped) < 5:
                    sample_dropped.append({"title": job.title, "company": job.company, "reason": "stale", "age_days": round(age, 1)})
                continue

            job_loc_lower = _normalize_location(job.location)
            location_match = any(loc in job_loc_lower for loc in profile_locations if loc)
            remote_match = "remote" in job.work_mode.lower() and "remote" in profile_work_modes
            if not location_match and not remote_match:
                dropped["location"] += 1
                if len(sample_dropped) < 5:
                    sample_dropped.append({"title": job.title, "company": job.company, "reason": "location"})
                continue

            if job.salary_lpa and job.salary_lpa.get("max") is not None and job.salary_lpa["max"] < salary_min:
                dropped["salary"] += 1
                continue

            if profile_company_types and "service" not in profile_company_types and job.company_type == "service":
                dropped["company_type"] += 1
                continue

            if job.company.lower() in exclude_companies:
                dropped["blocklist"] += 1
                continue

            passed.append(job)

        await _emit(conn, run_id, "filter_done", {
            "total_in": filter_in, "total_out": len(passed),
            "dropped_stale": dropped["stale"],
            "dropped_location": dropped["location"],
            "dropped_salary": dropped["salary"],
            "dropped_company_type": dropped["company_type"],
            "dropped_blocklist": dropped["blocklist"],
            "sample_dropped": sample_dropped,
        }, queue=event_queue)

        # Role filter
        rf_in = len(passed)
        passed, role_dropped = filter_by_role(passed)
        await _emit(conn, run_id, "role_filter_done", {
            "total_in": rf_in,
            "total_out": len(passed),
            "dropped": len(role_dropped),
            "sample_dropped": role_dropped[:5],
        }, queue=event_queue)

        # Rank
        ranked, rank_scores = rank_jobs(passed, profile, resume_summary)
        await _emit(conn, run_id, "rank_done", {
            "total_ranked": len(ranked),
            "top_scores": [round(s, 4) for s in rank_scores[:10]],
            "sent_to_scorer": min(50, len(ranked)),
        }, queue=event_queue)

        # Score
        model = config.SCORING_MODEL
        api_key = config.LLM_API_KEY
        to_score = ranked[:50]
        prompt_preview = _build_user_prompt(to_score, profile, resume_summary)[:300] if to_score else ""

        scored, tokens_used, cost_usd = await score_jobs(
            jobs=to_score, profile=profile, resume_summary=resume_summary,
            model=model, api_key=api_key,
        )
        scored.sort(key=lambda j: j.score, reverse=True)

        # Score distribution
        dist = {"0-3": 0, "4-6": 0, "7-10": 0}
        for j in scored:
            if j.score <= 3:
                dist["0-3"] += 1
            elif j.score <= 6:
                dist["4-6"] += 1
            else:
                dist["7-10"] += 1

        top_jobs_summary = [
            {"title": j.title, "company": j.company, "score": j.score}
            for j in scored[:5]
        ]

        await _emit(conn, run_id, "score_done", {
            "jobs_scored": len(scored),
            "chunks": 1,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "llm_prompt_preview": prompt_preview,
            "score_distribution": dist,
            "top_jobs": top_jobs_summary,
        }, queue=event_queue)

        # Write output JSON
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = config.OUTPUT_DIR / f"scored_jobs_{timestamp}.json"
        with open(output_path, "w") as fh:
            json.dump([asdict(j) for j in scored], fh, indent=2)

        duration = time.time() - started

        update_run(conn, run_id, {
            "jobs_found": total_raw,
            "jobs_scored": len(scored),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "output_file": str(output_path),
            "status": "completed",
            "duration_seconds": duration,
        })

        summary = {
            "run_id": run_id,
            "jobs_found": total_raw,
            "jobs_scored": len(scored),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "output_file": str(output_path),
            "duration_seconds": duration,
        }

        if event_queue is not None:
            await event_queue.put({"type": "done", "data": summary})
            await event_queue.put(None)

        return summary

    except Exception as exc:
        logger.exception("Pipeline failed")
        await _emit(conn, run_id, "error", {
            "step": "pipeline",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }, queue=event_queue)
        update_run(conn, run_id, {"status": "failed", "duration_seconds": time.time() - started})
        if event_queue is not None:
            await event_queue.put({"type": "done", "data": {"error": str(exc)}})
            await event_queue.put(None)
        raise


async def run() -> None:
    """CLI entry — full pipeline."""
    profile = _load_profile()
    conn = init_db(config.DB_PATH)
    run_id = insert_run(conn, {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "status": "running",
    })
    try:
        summary = await run_pipeline(conn, profile, run_id, event_queue=None)
        logger.info("Run complete: %s", summary)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------

def serve() -> None:
    import uvicorn
    uvicorn.run("roleminer.api.main:app", host="0.0.0.0", port=8000, reload=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "bootstrap":
        asyncio.run(bootstrap())
    elif cmd == "run":
        asyncio.run(run())
    elif cmd == "serve":
        serve()
    else:
        print(f"Unknown command: {cmd}. Use: bootstrap | run | serve")
        sys.exit(1)
