"""Ashby ATS scraper — public posting API."""
import re
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html or "")
    return " ".join(text.split())


def _detect_work_mode(title: str, content: str) -> str:
    combined = f"{title} {content}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    return "onsite"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _fetch(session: httpx.AsyncClient, url: str) -> dict:
    resp = await session.post(url, json={"limit": 100})
    resp.raise_for_status()
    return resp.json()


async def scrape(slug: str, session: httpx.AsyncClient, company_name: str = "") -> list[Job]:
    """
    Fetch all jobs from an Ashby board.

    Args:
        slug: Ashby company slug (e.g. "linear", "mercury")
        session: Shared HTTPX async client
        company_name: Override for company name

    Returns:
        List of Job objects. Empty list on failure.
    """
    url = _ASHBY_BASE.format(slug=slug)
    try:
        data = await _fetch(session, url)
    except Exception as exc:
        logger.warning("Ashby[%s] fetch failed: %s", slug, exc)
        return []

    jobs: list[Job] = []
    name = company_name or slug.replace("-", " ").title()

    for item in data.get("jobs", []):
        try:
            title = item.get("title", "")
            published_at = item.get("publishedAt", "")
            location = item.get("locationName", "")
            job_url = item.get("jobUrl", "")
            description_html = item.get("descriptionHtml", "")
            jd_text = _strip_html(description_html)
            work_mode = _detect_work_mode(title, jd_text)

            job = Job(
                title=title,
                company=name,
                url=job_url,
                date_posted=published_at,
                location=location,
                source="ashby",
                work_mode=work_mode,
                jd_text=jd_text,
            )
            jobs.append(job)
        except Exception as exc:
            logger.debug("Ashby[%s] skipping malformed job: %s", slug, exc)

    logger.info("Ashby[%s] fetched %d jobs", slug, len(jobs))
    return jobs
