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
from roleminer.registry.ats_detect import detect_ats_from_url, find_embedded_ats_url
from roleminer.registry.db import (
    init_db,
    insert_company,
    get_all_companies,
    insert_run,
    insert_run_event,
    update_run,
    update_last_scraped,
    clear_scrape_freshness,
    update_company_fields,
    update_company_embedding_id,
    upsert_job,
    replace_job_runs_for_run,
    update_job_runs_scores,
    ensure_default_user_id,
    get_active_profile_for_user,
    search_profile_row_to_pipeline_dict,
    SEED_COMPANIES,
)
from roleminer.registry import vector_store
from roleminer.pipeline import embedder
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


async def _resolve_careers_to_ats_url(session, careers_url: str) -> tuple[str, tuple[str, str] | None]:
    """
    GET the careers page (follow redirects). If the response URL is not an ATS board,
    scan HTML for embedded board URLs (iframe / links / JSON).
    Returns (url_to_use_for_detection, detect_ats_from_url result or None).
    """
    u = (careers_url or "").strip()
    if not u:
        logger.info("[careers-resolve] empty input — skip")
        return u, None
    logger.info("[careers-resolve] step=fetch url=%s", u)
    try:
        r = await session.get(u, follow_redirects=True, timeout=25.0)
        final = str(r.url)
        logger.info(
            "[careers-resolve] step=http status=%s final_url=%s (redirected=%s)",
            r.status_code,
            final,
            "yes" if final.rstrip("/") != u.rstrip("/") else "no",
        )
        if r.status_code >= 400:
            det = detect_ats_from_url(u)
            logger.info("[careers-resolve] step=detect(bad_status) on original url → %s", det)
            return u, det
        det = detect_ats_from_url(final)
        logger.info("[careers-resolve] step=detect(final_url) → %s", det)
        if det:
            return final, det
        html_len = len(r.text or "")
        logger.info("[careers-resolve] step=html_scan body_bytes=%s (no ATS in location bar)", html_len)
        embedded = find_embedded_ats_url(r.text)
        if embedded:
            det2 = detect_ats_from_url(embedded)
            logger.info(
                "[careers-resolve] step=embedded found=%s detect → %s",
                embedded,
                det2,
            )
            return embedded, det2
        logger.info("[careers-resolve] step=embedded none — corporate page had no board URL in HTML")
        return final, None
    except Exception as exc:
        logger.warning("[careers-resolve] step=error %s — fallback detect on original url", exc)
        det = detect_ats_from_url(u)
        logger.info("[careers-resolve] step=detect(fallback) → %s", det)
        return u, det


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def bootstrap() -> None:
    """Seed company registry with known Indian product companies."""
    logger.info("Bootstrapping company registry …")
    conn = init_db(config.DB_PATH)

    existing_rows = get_all_companies(conn)
    existing = {c["name"].lower() for c in existing_rows}
    inserted = 0
    new_companies: list[dict] = []

    for company in SEED_COMPANIES:
        if company["name"].lower() in existing:
            logger.info("  skip (exists): %s", company["name"])
            continue
        row_id = insert_company(conn, company)
        company = {**company, "id": row_id}
        new_companies.append(company)
        logger.info("  inserted [%d]: %s (%s / %s)", row_id, company["name"], company.get("ats_type"), company.get("ats_slug"))
        inserted += 1

    # Embed all companies that lack embedding_id
    if embedder.is_available():
        to_embed = [c for c in get_all_companies(conn) if not c.get("embedding_id")]
        if to_embed:
            logger.info("Embedding %d companies via %s …", len(to_embed), config.EMBED_MODEL)
            texts = [vector_store._company_text(c) for c in to_embed]
            vecs = embedder.embed_batched(texts, input_type="passage")
            chroma = vector_store.get_client(config.CHROMA_PATH)
            vector_store.upsert_companies(chroma, to_embed, vecs)
            for c in to_embed:
                update_company_embedding_id(conn, c["id"], str(c["id"]))
            logger.info("Embedded %d companies → ChromaDB", len(to_embed))
    else:
        logger.info("EMBED_API_KEY not set — skipping company embeddings")

    conn.close()
    logger.info("Bootstrap complete. Inserted %d companies (%d already existed).", inserted, len(existing))


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

async def _scrape_company(
    company: dict,
    session,
    profile: dict,
    conn: sqlite3.Connection | None = None,
) -> list[Job]:
    """Scrape one company, returning jobs. Errors are caught and logged."""
    ats_type = (company.get("ats_type") or "").strip()
    slug = (company.get("ats_slug") or "").strip()
    name = company.get("name", "")
    careers_url = (company.get("careers_url") or "").strip()
    cid = company.get("id")

    logger.info(
        "[scrape] company=%r id=%s initial ats_type=%r ats_slug=%r careers_url=%s",
        name,
        cid,
        ats_type,
        slug,
        careers_url or "(none)",
    )

    det: tuple[str, str] | None = None
    needs_resolve = bool(
        careers_url
        and (
            ats_type in ("", "custom")
            or (ats_type in ("greenhouse", "lever", "ashby") and not slug)
        )
    )
    if needs_resolve:
        logger.info(
            "[scrape] company=%r step=careers_resolve reason=%s",
            name,
            "custom_or_empty_ats" if ats_type in ("", "custom") else "missing_slug_for_known_ats",
        )
        resolved, det = await _resolve_careers_to_ats_url(session, careers_url)
        if det:
            ats_type, slug = det[0], (det[1] or "").strip()
            careers_url = resolved
        elif resolved != careers_url:
            careers_url = resolved
        logger.info(
            "[scrape] company=%r step=after_resolve ats_type=%r ats_slug=%r careers_url=%s det=%s",
            name,
            ats_type,
            slug,
            careers_url or "(none)",
            det,
        )
    else:
        logger.info(
            "[scrape] company=%r step=careers_resolve skipped (have slug or no careers_url for resolve)",
            name,
        )

    if conn and cid and det:
        patch: dict = {}
        if ats_type and ats_type != company.get("ats_type"):
            patch["ats_type"] = ats_type
        if slug and slug != (company.get("ats_slug") or ""):
            patch["ats_slug"] = slug
        new_cu = (careers_url or "").strip()
        if new_cu and new_cu != (company.get("careers_url") or "").strip():
            patch["careers_url"] = new_cu
        if patch:
            logger.info("[scrape] company=%r step=db_patch %s", name, patch)
            update_company_fields(conn, cid, patch)
            company.update(patch)
        else:
            logger.info("[scrape] company=%r step=db_patch none (already in sync)", name)
    elif conn and cid and not det:
        logger.info("[scrape] company=%r step=db_patch skipped (no new ATS from resolve)", name)

    if not slug and ats_type not in ("workday", "cutshort"):
        logger.warning(
            "[scrape] company=%r step=abort reason=no_ats_slug ats_type=%r careers_url=%s",
            name,
            ats_type,
            careers_url or "(none)",
        )
        return []

    try:
        logger.info("[scrape] company=%r step=call_scraper ats=%r slug=%r workday_url=%s", name, ats_type, slug, careers_url if ats_type == "workday" else "—")
        if ats_type == "greenhouse":
            jobs = await greenhouse.scrape(slug, session, company_name=name)
        elif ats_type == "lever":
            jobs = await lever.scrape(slug, session, company_name=name)
        elif ats_type == "ashby":
            jobs = await ashby.scrape(slug, session, company_name=name)
        elif ats_type == "workday":
            jobs = await workday.scrape(careers_url, session, company_name=name)
        elif ats_type == "cutshort":
            skills = profile.get("skills", [])
            locations = profile.get("locations", [])
            jobs = await cutshort.scrape(skills, locations, session)
        else:
            logger.warning("[scrape] company=%r step=abort unknown ats_type=%r", name, ats_type)
            return []
        logger.info("[scrape] company=%r step=done jobs_fetched=%s", name, len(jobs))
        return jobs
    except Exception as exc:
        logger.error("[scrape] company=%r step=error ats=%r slug=%r: %s", name, ats_type, slug, exc)
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
    user_id: int | None = None,
    event_queue: Optional[asyncio.Queue] = None,
) -> dict:
    """Full pipeline. Logs structured events to DB (and queue if provided)."""
    started = time.time()
    if user_id is not None:
        logger.info("run_pipeline run_id=%s user_id=%s", run_id, user_id)
    resume_summary = profile.get("resume_summary", "")
    companies = get_all_companies(conn)
    logger.info(
        "[pipeline] run_id=%s scrape phase: companies_in_registry=%d (Cutshort + each row)",
        run_id,
        len(companies),
    )

    all_jobs: list[Job] = []

    try:
        async with make_session(proxy_url=config.PROXY_URL) as session:
            total_companies = len(companies) + 1  # +1 for Cutshort
            await _emit(conn, run_id, "scrape_start", {
                "total_sources": total_companies,
                "freshness_hours": config.SCRAPER_FRESHNESS_HOURS,
                "companies": ["Cutshort"] + [c.get("name", "") for c in companies],
            }, queue=event_queue)

            # Cutshort (profile-level)
            t0 = time.time()
            await _emit(conn, run_id, "scraper_start", {
                "company": "Cutshort", "ats": "cutshort",
            }, source="Cutshort", queue=event_queue)
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

            freshness_hours = config.SCRAPER_FRESHNESS_HOURS
            skipped_fresh: list[str] = []

            for company in companies:
                last = company.get("last_scraped_at")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        hours_ago = (datetime.now(tz=timezone.utc) - last_dt).total_seconds() / 3600
                        if hours_ago < freshness_hours:
                            skipped_fresh.append(company.get("name", ""))
                            logger.info(
                                "[scrape] company=%r step=skipped_fresh last_scraped_hours_ago=%.1f freshness_hours=%s",
                                company.get("name"),
                                hours_ago,
                                freshness_hours,
                            )
                            await _emit(conn, run_id, "scraper_skipped", {
                                "company": company.get("name"),
                                "ats": company.get("ats_type"),
                                "last_scraped_hours_ago": round(hours_ago, 1),
                                "freshness_hours": freshness_hours,
                            }, source=company.get("name", ""), queue=event_queue)
                            continue
                    except (ValueError, TypeError):
                        pass  # malformed ts → scrape anyway

                t0 = time.time()
                await _emit(conn, run_id, "scraper_start", {
                    "company": company.get("name"), "ats": company.get("ats_type"),
                }, source=company.get("name", ""), queue=event_queue)
                err = None
                try:
                    jobs = await _scrape_company(company, session, profile, conn)
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

        # Auto-discover new companies from scraped job URLs
        existing_names = {c["name"].lower() for c in get_all_companies(conn)}
        discovered: list[dict] = []
        seen_new: set[str] = set()
        pd_skip_existing = pd_skip_dup = pd_skip_not_ats = pd_skip_no_name = 0
        for job in all_jobs:
            name_lower = (job.company or "").lower().strip()
            if not name_lower:
                pd_skip_no_name += 1
                continue
            if name_lower in existing_names:
                pd_skip_existing += 1
                continue
            if name_lower in seen_new:
                pd_skip_dup += 1
                continue
            result = detect_ats_from_url(job.url or "")
            if not result:
                pd_skip_not_ats += 1
                continue
            ats_type, slug = result
            new_co: dict = {
                "name": job.company,
                "ats_type": ats_type,
                "ats_slug": slug,
                "company_type": job.company_type or "product",
            }
            if ats_type == "workday" and "/wday/cxs/" in (job.url or ""):
                new_co["careers_url"] = job.url.split("?")[0]
            row_id = insert_company(conn, new_co)
            new_co["id"] = row_id
            discovered.append(new_co)
            seen_new.add(name_lower)
            logger.info(
                "[pipeline-discover] insert company=%r ats=%s/%s job_url=%s db_id=%s careers_url=%s",
                job.company,
                ats_type,
                slug,
                job.url,
                row_id,
                new_co.get("careers_url") or "(none)",
            )
        logger.info(
            "[pipeline-discover] summary jobs_scanned=%d new_companies=%d skip_no_name=%d skip_in_registry=%d skip_dup_run=%d skip_url_not_ats=%d",
            len(all_jobs),
            len(discovered),
            pd_skip_no_name,
            pd_skip_existing,
            pd_skip_dup,
            pd_skip_not_ats,
        )
        await _emit(conn, run_id, "discover_done", {
            "new_companies": len(discovered),
            "names": [c["name"] for c in discovered],
        }, queue=event_queue)

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

        for job in passed:
            upsert_job(conn, asdict(job))

        # Embed + persist all filter-passing jobs to ChromaDB
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

        # Rank
        ranked, rank_scores = rank_jobs(passed, profile, resume_summary)
        replace_job_runs_for_run(conn, run_id, [asdict(j) for j in ranked], rank_scores)
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
        update_job_runs_scores(conn, run_id, [asdict(j) for j in scored])

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
