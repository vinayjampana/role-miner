"""Cutshort scraper — India-first public search API."""
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_CUTSHORT_URL = "https://cutshort.io/api/public/jobs"


def _detect_work_mode(title: str = "", location: str = "") -> str:
    combined = f"{title} {location}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    return "onsite"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _fetch(session: httpx.AsyncClient, params: dict) -> httpx.Response:
    return await session.get(_CUTSHORT_URL, params=params)


async def scrape(
    skills: list[str],
    locations: list[str],
    session: httpx.AsyncClient,
) -> list[Job]:
    """
    Fetch jobs from Cutshort public API.

    Returns empty list on 401/403 (auth required). Handles response defensively.

    Args:
        skills: List of skills from profile (e.g. ["React", "TypeScript"])
        locations: List of locations from profile (e.g. ["Bangalore", "Remote"])
        session: Shared HTTPX async client
    """
    params: dict = {}
    if skills:
        params["skills"] = ",".join(skills)
    if locations:
        params["location"] = ",".join(locations)
    params["role"] = "engineer"

    try:
        resp = await _fetch(session, params)
    except Exception as exc:
        logger.warning("Cutshort fetch failed: %s", exc)
        return []

    if resp.status_code in (401, 403):
        logger.warning("Cutshort returned %d — auth required, skipping", resp.status_code)
        return []

    if resp.status_code != 200:
        logger.warning("Cutshort returned HTTP %d", resp.status_code)
        return []

    try:
        body = resp.json()
    except Exception:
        logger.warning("Cutshort response is not JSON")
        return []

    # Handle both {"data": [...]} and direct list shapes defensively
    raw_jobs = body.get("data", []) if isinstance(body, dict) else []
    if not isinstance(raw_jobs, list):
        raw_jobs = []

    jobs: list[Job] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        try:
            title = item.get("title", "")
            company_info = item.get("company") or {}
            company_name = (
                company_info.get("name", "") if isinstance(company_info, dict) else str(company_info)
            )
            url = item.get("url", "")
            posted_at = item.get("posted_at", "")
            location = item.get("location", "")
            salary_raw = item.get("salary")  # already in LPA from Cutshort

            salary_lpa = None
            if isinstance(salary_raw, dict):
                s_min = salary_raw.get("min")
                s_max = salary_raw.get("max")
                if s_min is not None or s_max is not None:
                    salary_lpa = {"min": s_min, "max": s_max}

            work_mode = _detect_work_mode(title, location)

            job = Job(
                title=title,
                company=company_name,
                url=url,
                date_posted=posted_at,
                location=location,
                source="cutshort",
                work_mode=work_mode,
                salary_lpa=salary_lpa,
            )
            jobs.append(job)
        except Exception as exc:
            logger.debug("Cutshort skipping malformed job: %s", exc)

    logger.info("Cutshort fetched %d jobs", len(jobs))
    return jobs
