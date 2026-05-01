"""Lever ATS scraper — public REST API."""
import re
import logging
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_LEVER_BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"


def _strip_html(html: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    text = _TAG_RE.sub(" ", html or "")
    return " ".join(text.split())


def _detect_work_mode(title: str, content: str) -> str:
    combined = f"{title} {content}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    return "onsite"


def _unix_ms_to_iso(ms: int) -> str:
    """Convert unix milliseconds to ISO 8601 UTC string."""
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _fetch(session: httpx.AsyncClient, url: str) -> list:
    resp = await session.get(url)
    resp.raise_for_status()
    return resp.json()


async def scrape(slug: str, session: httpx.AsyncClient, company_name: str = "") -> list[Job]:
    """
    Fetch all jobs from a Lever board.

    Args:
        slug: Lever company slug (e.g. "reddit", "stripe")
        session: Shared HTTPX async client
        company_name: Override for company name (uses slug title-case if empty)

    Returns:
        List of Job objects. Empty list on failure.
    """
    url = _LEVER_BASE.format(slug=slug)
    try:
        data = await _fetch(session, url)
    except Exception as exc:
        logger.warning("Lever[%s] fetch failed: %s", slug, exc)
        return []

    if not isinstance(data, list):
        logger.warning("Lever[%s] unexpected response shape", slug)
        return []

    jobs: list[Job] = []
    name = company_name or slug.replace("-", " ").title()

    for item in data:
        try:
            title = item.get("text", "")
            created_at_ms = item.get("createdAt", 0)
            date_posted = _unix_ms_to_iso(created_at_ms) if created_at_ms else ""
            hosted_url = item.get("hostedUrl", "")
            categories = item.get("categories") or {}
            location = categories.get("location", "")

            # Build jd_text from description + lists
            description_html = item.get("description", "")
            lists_html = " ".join(
                lst.get("content", "") for lst in (item.get("lists") or [])
            )
            jd_text = _strip_html(f"{description_html} {lists_html}")
            work_mode = _detect_work_mode(title, jd_text)

            job = Job(
                title=title,
                company=name,
                url=hosted_url,
                date_posted=date_posted,
                location=location,
                source="lever",
                work_mode=work_mode,
                jd_text=jd_text,
            )
            jobs.append(job)
        except Exception as exc:
            logger.debug("Lever[%s] skipping malformed job: %s", slug, exc)

    logger.info("Lever[%s] fetched %d jobs", slug, len(jobs))
    return jobs
