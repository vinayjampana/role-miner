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

import config
import re as _re

# V1: ats_detect, job_api_discover kept for reference but not called in pipeline
from roleminer.registry.db import (
    init_db,
    insert_run,
    insert_run_event,
    update_run,
    clear_scrape_freshness,
    update_company_embedding_id,
    upsert_job,
    replace_job_runs_for_run,
    update_job_runs_scores,
    ensure_default_user_id,
    get_active_profile_for_user,
    search_profile_row_to_pipeline_dict,
    get_freshness_by_name,
    set_freshness_by_name,
)
from roleminer.registry.static_registry import load_companies
from roleminer.registry import vector_store
from roleminer.pipeline import embedder
from roleminer.scrapers.base import Job, dedup_by_url, dedup_fuzzy, make_session
from roleminer.scrapers import greenhouse, workday
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


# V1: _scan_js_chunks_for_ats and _resolve_careers_to_ats_url disabled (ATS detection not used)
# kept in git history; re-enable when supporting custom/unknown ATS


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def bootstrap() -> None:
    """Embed static company registry into ChromaDB for semantic search."""
    logger.info("Bootstrapping — loading static registry and embedding companies …")
    companies = load_companies()
    logger.info("Static registry: %d companies", len(companies))

    if embedder.is_available():
        # Map static registry shape to vector_store expected shape
        co_docs = [{"name": c["company"], "ats_type": c["ats"], "careers_url": c.get("careers_url", "")} for c in companies]
        texts = [vector_store._company_text(c) for c in co_docs]
        vecs = embedder.embed_batched(texts, input_type="passage")
        chroma = vector_store.get_client(config.CHROMA_PATH)
        vector_store.upsert_companies(chroma, co_docs, vecs)
        logger.info("Embedded %d companies → ChromaDB", len(companies))
    else:
        logger.info("EMBED_API_KEY not set — skipping company embeddings")

    logger.info("Bootstrap complete.")


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

async def _scrape_company(
    company: dict,
    session,
    conn: sqlite3.Connection | None = None,
) -> tuple[list[Job], str]:
    """
    Scrape one company. Routes to Greenhouse or Workday HTTP scraper.
    Falls back to Playwright if HTTP returns zero jobs.
    Returns (jobs, method) where method is "http" or "playwright".
    """
    ats = company.get("ats", "").strip()
    name = company.get("company", "")
    careers_url = (company.get("careers_url") or "").strip()
    slug = (company.get("slug") or "").strip()

    logger.info("[scrape] company=%r ats=%r", name, ats)

    jobs: list[Job] = []
    http_ok = False

    if ats == "greenhouse":
        try:
            jobs = await greenhouse.scrape(slug, session, company_name=name)
            http_ok = True
        except Exception as exc:
            logger.warning("[scrape] greenhouse[%s] http failed: %s", name, exc)
    elif ats == "workday":
        try:
            jobs = await workday.scrape(careers_url, session, company_name=name)
            http_ok = True
        except Exception as exc:
            logger.warning("[scrape] workday[%s] http failed: %s", name, exc)
    else:
        logger.warning("[scrape] unsupported ats=%r company=%r — skip", ats, name)
        return [], "none"

    if jobs:
        logger.info("[scrape] company=%r method=http jobs=%d", name, len(jobs))
        return jobs, "http"

    # HTTP returned nothing or failed — Playwright fallback
    logger.info("[scrape] company=%r http=0 → playwright fallback url=%s", name, careers_url)
    if careers_url:
        try:
            from roleminer.scrapers import custom as custom_scraper
            jobs = await custom_scraper.scrape(careers_url, company_name=name)
            if jobs:
                logger.info("[scrape] company=%r method=playwright jobs=%d", name, len(jobs))
                return jobs, "playwright"
            logger.info("[scrape] company=%r playwright=0", name)
        except Exception as exc:
            logger.warning("[scrape] company=%r playwright fallback failed: %s", name, exc)

    return [], "playwright" if not http_ok else "http"


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


# Cap job rows stored per run event (full title/company/url); keeps SQLite payloads bounded.
_RUN_LOG_JOB_LIST_CAP = 200


def _run_log_job_items(jobs: list, cap: int | None = None) -> dict:
    c = cap if cap is not None else _RUN_LOG_JOB_LIST_CAP
    items = [{"title": j.title, "company": j.company, "url": j.url} for j in jobs[:c]]
    return {"total": len(jobs), "truncated": len(jobs) > c, "items": items}


def _run_log_ranked_jobs(jobs: list, scores: list[float], cap: int | None = None) -> dict:
    c = cap if cap is not None else _RUN_LOG_JOB_LIST_CAP
    items: list[dict] = []
    for i, j in enumerate(jobs[:c]):
        row = {"title": j.title, "company": j.company, "url": j.url}
        if i < len(scores):
            row["rank_score"] = round(float(scores[i]), 4)
        items.append(row)
    return {"total": len(jobs), "truncated": len(jobs) > c, "items": items}


def _run_log_scored_jobs(scored: list, cap: int = 55) -> dict:
    items = [
        {"title": j.title, "company": j.company, "url": j.url, "score": j.score}
        for j in scored[:cap]
    ]
    return {"total": len(scored), "truncated": len(scored) > cap, "items": items}


# ---------------------------------------------------------------------------
# run_pipeline — callable from CLI or FastAPI
# ---------------------------------------------------------------------------

async def run_pipeline(
    conn: sqlite3.Connection,
    profile: dict,
    run_id: int,
    user_id: int | None = None,
    event_queue: Optional[asyncio.Queue] = None,
) -> dict:
    """Full pipeline. Logs structured events to DB (and queue if provided)."""
    started = time.time()
    if user_id is not None:
        logger.info("run_pipeline run_id=%s user_id=%s", run_id, user_id)
    resume_summary = profile.get("resume_summary", "")
    companies = load_companies()
    logger.info(
        "[pipeline] run_id=%s scrape phase: companies_in_registry=%d",
        run_id,
        len(companies),
    )

    all_jobs: list[Job] = []

    try:
        async with make_session(proxy_url=config.PROXY_URL) as session:
            await _emit(conn, run_id, "scrape_start", {
                "total_sources": len(companies),
                "freshness_hours": config.SCRAPER_FRESHNESS_HOURS,
                "companies": [c.get("company", "") for c in companies],
            }, queue=event_queue)

            freshness_hours = config.SCRAPER_FRESHNESS_HOURS

            for company in companies:
                name = company.get("company", "")
                last = get_freshness_by_name(conn, name)
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        hours_ago = (datetime.now(tz=timezone.utc) - last_dt).total_seconds() / 3600
                        if hours_ago < freshness_hours:
                            logger.info(
                                "[scrape] company=%r step=skipped_fresh hours_ago=%.1f",
                                name, hours_ago,
                            )
                            await _emit(conn, run_id, "scraper_skipped", {
                                "company": name,
                                "ats": company.get("ats"),
                                "last_scraped_hours_ago": round(hours_ago, 1),
                                "freshness_hours": freshness_hours,
                            }, source=name, queue=event_queue)
                            continue
                    except (ValueError, TypeError):
                        pass

                t0 = time.time()
                await _emit(conn, run_id, "scraper_start", {
                    "company": name, "ats": company.get("ats"),
                }, source=name, queue=event_queue)
                err = None
                scraper_method = "http"
                try:
                    jobs, scraper_method = await _scrape_company(company, session, conn)
                except Exception as exc:
                    jobs = []
                    err = str(exc)
                    await _emit(conn, run_id, "error", {
                        "step": "scraper", "company": name,
                        "error": err, "traceback": traceback.format_exc(),
                    }, source=name, queue=event_queue)
                all_jobs.extend(jobs)
                if jobs:
                    set_freshness_by_name(conn, name)
                await _emit(conn, run_id, "scraper_done", {
                    "company": name,
                    "ats": company.get("ats"),
                    "scraper_method": scraper_method,
                    "jobs_fetched": len(jobs),
                    "duration_ms": int((time.time() - t0) * 1000),
                    "error": err,
                }, source=name, queue=event_queue)

        total_raw = len(all_jobs)

        await _emit(conn, run_id, "scrape_done", {
            "total_jobs": total_raw,
            "scraped_count": total_raw,
        }, queue=event_queue)

        await _pipeline_post_scrape(conn, run_id, all_jobs, profile, started, event_queue)

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


async def _pipeline_post_scrape(
    conn: sqlite3.Connection,
    run_id: int,
    all_jobs: list[Job],
    profile: dict,
    started: float,
    event_queue: Optional[asyncio.Queue] = None,
) -> dict:
    resume_summary = profile.get("resume_summary", "")
    total_raw = len(all_jobs)

    # V1: company auto-discovery disabled (static registry only)

    n_pre_dedup = len(all_jobs)
    all_jobs = dedup_fuzzy(all_jobs)  # URL + fuzzy title+company+location
    dedup_jobs_snap = _run_log_job_items(all_jobs)
    await _emit(conn, run_id, "dedup_done", {
        "total_in": n_pre_dedup,
        "total_out": len(all_jobs),
        "removed": n_pre_dedup - len(all_jobs),
        "deduped_count": len(all_jobs),
        "jobs": dedup_jobs_snap,
    }, queue=event_queue)
    logger.info(
        "[pipeline] run_id=%s dedup_done in=%d out=%d removed=%d",
        run_id,
        n_pre_dedup,
        len(all_jobs),
        n_pre_dedup - len(all_jobs),
    )

    for job in all_jobs:
        if not job.company_type:
            job.company_type = classify_company(job.company, job.jd_text)
        if not job.work_mode or job.work_mode == "onsite":
            job.work_mode = detect_work_mode(job.title, job.jd_text, job.location)

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
                sample_dropped.append({
                    "title": job.title, "company": job.company, "url": job.url,
                    "reason": "stale", "age_days": round(age, 1),
                })
            continue

        job_loc_lower = _normalize_location(job.location)
        location_match = any(loc in job_loc_lower for loc in profile_locations if loc)
        remote_match = "remote" in job.work_mode.lower() and "remote" in profile_work_modes
        if not location_match and not remote_match:
            dropped["location"] += 1
            if len(sample_dropped) < 5:
                sample_dropped.append({
                    "title": job.title, "company": job.company, "url": job.url,
                    "reason": "location",
                })
            continue

        if job.salary_lpa and job.salary_lpa.get("max") is not None and job.salary_lpa["max"] < salary_min:
            dropped["salary"] += 1
            if len(sample_dropped) < 5:
                sample_dropped.append({
                    "title": job.title, "company": job.company, "url": job.url,
                    "reason": "salary",
                })
            continue

        if profile_company_types and "service" not in profile_company_types and job.company_type == "service":
            dropped["company_type"] += 1
            if len(sample_dropped) < 5:
                sample_dropped.append({
                    "title": job.title, "company": job.company, "url": job.url,
                    "reason": "company_type",
                })
            continue

        if job.company.lower() in exclude_companies:
            dropped["blocklist"] += 1
            if len(sample_dropped) < 5:
                sample_dropped.append({
                    "title": job.title, "company": job.company, "url": job.url,
                    "reason": "blocklist",
                })
            continue

        passed.append(job)

    filter_passed_snap = _run_log_job_items(passed)
    await _emit(conn, run_id, "filter_done", {
        "total_in": filter_in, "total_out": len(passed),
        "filtered_count": len(passed),
        "dropped_stale": dropped["stale"],
        "dropped_location": dropped["location"],
        "dropped_salary": dropped["salary"],
        "dropped_company_type": dropped["company_type"],
        "dropped_blocklist": dropped["blocklist"],
        "sample_dropped": sample_dropped,
        "jobs_passed": filter_passed_snap,
    }, queue=event_queue)
    logger.info(
        "[pipeline] run_id=%s filter_done in=%d out=%d event_items=%d truncated=%s dropped=%s",
        run_id,
        filter_in,
        len(passed),
        len(filter_passed_snap["items"]),
        filter_passed_snap["truncated"],
        dict(dropped),
    )

    rf_in = len(passed)
    passed, role_dropped = filter_by_role(passed)
    role_passed_snap = _run_log_job_items(passed)
    await _emit(conn, run_id, "role_filter_done", {
        "total_in": rf_in,
        "total_out": len(passed),
        "dropped": len(role_dropped),
        "sample_dropped": role_dropped[:15],
        "jobs_passed": role_passed_snap,
    }, queue=event_queue)
    logger.info(
        "[pipeline] run_id=%s role_filter_done in=%d out=%d event_items=%d truncated=%s role_dropped=%d",
        run_id,
        rf_in,
        len(passed),
        len(role_passed_snap["items"]),
        role_passed_snap["truncated"],
        len(role_dropped),
    )

    for job in passed:
        upsert_job(conn, asdict(job))

    if embedder.is_available() and passed:
        try:
            job_texts = [vector_store._job_text(j) for j in passed]
            job_vecs = embedder.embed_batched(job_texts, input_type="passage")
            chroma = vector_store.get_client(config.CHROMA_PATH)
            vector_store.upsert_jobs(chroma, passed, run_id, job_vecs)
            await _emit(conn, run_id, "embed_done", {
                "jobs_embedded": len(passed),
                "model": config.EMBED_MODEL,
            }, queue=event_queue)
        except Exception as exc:
            logger.warning("Job embedding failed: %s", exc)

    ranked, rank_scores = rank_jobs(passed, profile, resume_summary)
    replace_job_runs_for_run(conn, run_id, [asdict(j) for j in ranked], rank_scores)
    ranked_snap = _run_log_ranked_jobs(ranked, rank_scores)
    _SCORE_TOP_N = 20
    await _emit(conn, run_id, "rank_done", {
        "total_ranked": len(ranked),
        "ranked_count": len(ranked),
        "top_scores": [round(s, 4) for s in rank_scores[:10]],
        "sent_to_scorer": min(_SCORE_TOP_N, len(ranked)),
        "jobs_ranked": ranked_snap,
    }, queue=event_queue)
    logger.info(
        "[pipeline] run_id=%s rank_done total=%d top_score=%s",
        run_id,
        len(ranked),
        round(float(rank_scores[0]), 4) if rank_scores else None,
    )

    model = config.SCORING_MODEL
    api_key = config.LLM_API_KEY
    to_score = ranked[:_SCORE_TOP_N]
    prompt_preview = _build_user_prompt(to_score, profile, resume_summary)[:300] if to_score else ""

    scored, tokens_used, cost_usd = await score_jobs(
        jobs=to_score, profile=profile, resume_summary=resume_summary,
        model=model, api_key=api_key,
    )
    scored.sort(key=lambda j: j.score, reverse=True)
    update_job_runs_scores(conn, run_id, [asdict(j) for j in scored])

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
    scored_list_snap = _run_log_scored_jobs(scored, cap=55)

    await _emit(conn, run_id, "score_done", {
        "jobs_scored": len(scored),
        "scored_count": len(scored),
        "chunks": 1,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "llm_prompt_preview": prompt_preview,
        "score_distribution": dist,
        "top_jobs": top_jobs_summary,
        "jobs_scored_detail": scored_list_snap,
    }, queue=event_queue)
    logger.info(
        "[pipeline] run_id=%s score_done scored=%d event_items=%d truncated=%s tokens=%s cost_usd=%s",
        run_id,
        len(scored),
        len(scored_list_snap["items"]),
        scored_list_snap["truncated"],
        tokens_used,
        round(cost_usd, 6) if cost_usd else 0,
    )

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


def reset_scrape_freshness_cli() -> None:
    """Clear per-company last_scraped_at so the next pipeline run scrapes all companies."""
    conn = init_db(config.DB_PATH)
    try:
        n = clear_scrape_freshness(conn)
        logger.info("Cleared last_scraped_at on %d companies — next run will scrape all (ignores freshness window).", n)
    finally:
        conn.close()


async def run() -> None:
    """CLI entry — full pipeline."""
    import argparse

    parser = argparse.ArgumentParser(prog="python main.py run")
    parser.add_argument("--user", type=str, default=None, help="User name (default: user id 1)")
    args = parser.parse_args(sys.argv[2:] if len(sys.argv) > 2 else [])

    conn = init_db(config.DB_PATH)
    try:
        if args.user:
            row = conn.execute(
                "SELECT id, active_profile_id FROM users WHERE name = ?",
                (args.user.strip(),),
            ).fetchone()
            if not row:
                logger.error("Unknown user: %s", args.user)
                sys.exit(1)
            uid = int(row["id"])
            apid = row["active_profile_id"]
        else:
            uid = ensure_default_user_id(conn)
            _, pr = get_active_profile_for_user(conn, uid)
            apid = pr["id"] if pr else None
        if not apid:
            logger.error("User has no active profile")
            sys.exit(1)
        prow = conn.execute("SELECT * FROM search_profiles WHERE id = ?", (int(apid),)).fetchone()
        if not prow:
            logger.error("Profile row missing")
            sys.exit(1)
        profile = search_profile_row_to_pipeline_dict(dict(prow))

        run_id = insert_run(conn, {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "status": "running",
            "user_id": uid,
            "search_profile_id": int(apid),
        })
        summary = await run_pipeline(conn, profile, run_id, user_id=uid, event_queue=None)
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
    if len(sys.argv) < 2:
        print(
            "Usage: python main.py bootstrap | run | serve | reset-scrape\n"
            "  bootstrap    — seed company registry\n"
            "  run            — scrape → rank → score (CLI pipeline)\n"
            "  serve          — FastAPI only (no scrape on start)\n"
            "  reset-scrape   — clear last_scraped_at on all companies (re-scrape everything next run)",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "bootstrap":
        asyncio.run(bootstrap())
    elif cmd == "run":
        asyncio.run(run())
    elif cmd == "serve":
        serve()
    elif cmd == "reset-scrape":
        reset_scrape_freshness_cli()
    else:
        print(f"Unknown command: {cmd}. Use: bootstrap | run | serve | reset-scrape", file=sys.stderr)
        sys.exit(1)
