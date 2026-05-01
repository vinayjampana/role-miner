"""Greenhouse ATS scraper — public REST API."""
import re
import logging
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _strip_html(html: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    text = _TAG_RE.sub(" ", html or "")
    return " ".join(text.split())


def _detect_work_mode(title: str, content: str) -> str:
    """Detect work mode from title + JD content."""
    combined = f"{title} {content}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    return "onsite"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _fetch(session: httpx.AsyncClient, url: str) -> dict:
    resp = await session.get(url)
    resp.raise_for_status()
    return resp.json()


async def scrape(slug: str, session: httpx.AsyncClient, company_name: str = "") -> list[Job]:
    """
    Fetch all jobs from a Greenhouse board.

    Args:
        slug: Greenhouse board slug (e.g. "postman", "razorpay")
        session: Shared HTTPX async client
        company_name: Override for company name (uses slug if empty)

    Returns:
        List of Job objects. Empty list on failure.
    """
    url = f"{_GREENHOUSE_BASE.format(slug=slug)}?content=true"
    try:
        data = await _fetch(session, url)
    except Exception as exc:
        logger.warning("Greenhouse[%s] fetch failed: %s", slug, exc)
        return []

    jobs: list[Job] = []
    name = company_name or slug.replace("-", " ").title()

    for item in data.get("jobs", []):
        try:
            title = item.get("title", "")
            location = (item.get("location") or {}).get("name", "")
            absolute_url = item.get("absolute_url", "")
            updated_at = item.get("updated_at", "")
            content_html = item.get("content", "")
            jd_text = _strip_html(content_html)
            work_mode = _detect_work_mode(title, jd_text)

            job = Job(
                title=title,
                company=name,
                url=absolute_url,
                date_posted=updated_at,
                location=location,
                source="greenhouse",
                work_mode=work_mode,
                jd_text=jd_text,
            )
            jobs.append(job)
        except Exception as exc:
            logger.debug("Greenhouse[%s] skipping malformed job: %s", slug, exc)

    logger.info("Greenhouse[%s] fetched %d jobs", slug, len(jobs))
    return jobs
