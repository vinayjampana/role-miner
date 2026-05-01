#!/usr/bin/env python3
"""
RoleMiner CLI

Usage:
  python main.py bootstrap   # seed company registry
  python main.py run         # scrape → filter → score → output JSON
"""
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

import config
from roleminer.registry.db import (
    init_db,
    insert_company,
    get_all_companies,
    insert_run,
    update_last_scraped,
    SEED_COMPANIES,
)
from roleminer.scrapers.base import Job, dedup_by_url, make_session
from roleminer.scrapers import greenhouse, lever, ashby, cutshort
from roleminer.pipeline.classifier import classify_company
from roleminer.pipeline.filter import filter_jobs, detect_work_mode
from roleminer.pipeline.scorer import score_jobs

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
# Run
# ---------------------------------------------------------------------------

def _load_profile() -> dict:
    with open(config.SEARCH_PROFILE, "r") as fh:
        return yaml.safe_load(fh)


async def _scrape_company(company: dict, session, profile: dict) -> list[Job]:
    """Scrape one company, returning jobs. Errors are caught and logged."""
    ats_type = company.get("ats_type", "")
    slug = company.get("ats_slug", "")
    name = company.get("name", "")

    if not slug:
        logger.warning("Company '%s' has no ats_slug — skipping", name)
        return []

    try:
        if ats_type == "greenhouse":
            return await greenhouse.scrape(slug, session, company_name=name)
        elif ats_type == "lever":
            return await lever.scrape(slug, session, company_name=name)
        elif ats_type == "ashby":
            return await ashby.scrape(slug, session, company_name=name)
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


async def run() -> None:
    """Full pipeline: scrape → filter → classify → score → write JSON."""
    profile = _load_profile()
    resume_summary = profile.get("resume_summary", "")

    conn = init_db(config.DB_PATH)
    companies = get_all_companies(conn)

    if not companies:
        logger.warning("No companies in registry. Run `python main.py bootstrap` first.")

    logger.info("Scraping %d companies …", len(companies))

    all_jobs: list[Job] = []

    async with make_session(proxy_url=config.PROXY_URL) as session:
        # Scrape Cutshort separately (profile-level, not per-company)
        cs_jobs = await cutshort.scrape(
            skills=profile.get("skills", []),
            locations=profile.get("locations", []),
            session=session,
        )
        all_jobs.extend(cs_jobs)

        for company in companies:
            jobs = await _scrape_company(company, session, profile)
            all_jobs.extend(jobs)
            if jobs and company.get("id"):
                update_last_scraped(conn, company["id"])

    logger.info("Total raw jobs: %d", len(all_jobs))

    # Dedup by URL
    all_jobs = dedup_by_url(all_jobs)
    logger.info("After dedup: %d jobs", len(all_jobs))

    # Classify company type + detect work_mode
    for job in all_jobs:
        if not job.company_type:
            job.company_type = classify_company(job.company, job.jd_text)
        if not job.work_mode or job.work_mode == "onsite":
            # Re-detect from JD text (scrapers do a basic check, do it again with full text)
            job.work_mode = detect_work_mode(job.title, job.jd_text, job.location)

    # Filter
    filtered = filter_jobs(all_jobs, profile)
    logger.info("After filter: %d jobs", len(filtered))

    # Score top 50
    model = config.SCORING_MODEL
    api_key = config.OPENAI_API_KEY or config.DEEPSEEK_API_KEY

    scored, tokens_used, cost_usd = await score_jobs(
        jobs=filtered[:50],
        profile=profile,
        resume_summary=resume_summary,
        model=model,
        api_key=api_key,
    )

    # Sort by score descending
    scored.sort(key=lambda j: j.score, reverse=True)

    # Write output
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = config.OUTPUT_DIR / f"scored_jobs_{timestamp}.json"

    with open(output_path, "w") as fh:
        json.dump([asdict(j) for j in scored], fh, indent=2)

    logger.info("Written: %s", output_path)
    logger.info("Jobs: raw=%d deduped=%d filtered=%d scored=%d", len(all_jobs), len(all_jobs), len(filtered), len(scored))
    logger.info("Tokens used: %d | Cost: $%.6f (≈₹%.2f)", tokens_used, cost_usd, cost_usd * 83)

    # Record run
    insert_run(conn, {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "jobs_found": len(all_jobs),
        "jobs_scored": len(scored),
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "output_file": str(output_path),
    })
    conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "bootstrap":
        asyncio.run(bootstrap())
    elif cmd == "run":
        asyncio.run(run())
    else:
        print(f"Unknown command: {cmd}. Use: bootstrap | run")
        sys.exit(1)
