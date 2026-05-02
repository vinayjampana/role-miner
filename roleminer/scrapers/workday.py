"""Workday ATS scraper — unofficial JSON API per company tenant."""
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _post(session: httpx.AsyncClient, url: str, body: dict, headers: dict) -> dict:
    resp = await session.post(url, json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _parse_posted_on(text: str) -> str:
    """
    Parse Workday's "Posted X Days Ago" string.

    Returns ISO 8601 UTC timestamp.
    """
    if not text:
        return datetime.now(tz=timezone.utc).isoformat()

    t = text.lower().strip()
    now = datetime.now(tz=timezone.utc)

    if "today" in t:
        return now.isoformat()
    if "yesterday" in t:
        return (now - timedelta(days=1)).isoformat()
    if "30+" in t:
        return (now - timedelta(days=31)).isoformat()

    m = re.search(r"(\d+)\s*day", t)
    if m:
        days = int(m.group(1))
        return (now - timedelta(days=days)).isoformat()

    m = re.search(r"(\d+)\s*month", t)
    if m:
        return (now - timedelta(days=int(m.group(1)) * 30)).isoformat()

    return now.isoformat()


def _build_job_url(careers_url: str, external_path: str) -> str:
    """
    Build job URL from POST URL + externalPath.

    careers_url: "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs"
    external_path: "/job/Hyderabad/Senior-SWE_R0012345"
    → "https://paypal.wd1.myworkdayjobs.com/en-US/jobs/job/Hyderabad/Senior-SWE_R0012345"
    """
    parsed = urlparse(careers_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Path looks like: /wday/cxs/{subdomain}/{tenant}/jobs
    parts = parsed.path.strip("/").split("/")
    tenant = parts[3] if len(parts) > 3 else ""
    return f"{base}/en-US/{tenant}{external_path}"


async def scrape(careers_url: str, session: httpx.AsyncClient, company_name: str = "") -> list[Job]:
    """
    Fetch jobs from a Workday tenant.

    careers_url is the full POST endpoint stored in companies.careers_url.
    """
    if not careers_url:
        return []

    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "engineer"}
    parsed = urlparse(careers_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": origin,
        "Referer": origin + "/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    }

    try:
        data = await _post(session, careers_url, body, headers)
    except Exception as exc:
        logger.warning("Workday[%s] fetch failed: %s", company_name or careers_url, exc)
        return []

    jobs: list[Job] = []
    name = company_name or "Unknown"

    for item in data.get("jobPostings", []):
        try:
            title = item.get("title", "")
            external_path = item.get("externalPath", "")
            location = item.get("locationsText") or ""
            if not location and item.get("bulletFields"):
                location = item["bulletFields"][0]
            posted_on = item.get("postedOn", "")
            date_iso = _parse_posted_on(posted_on)

            url = _build_job_url(careers_url, external_path)

            combined = f"{title} {location}".lower()
            work_mode = "remote" if "remote" in combined else ("hybrid" if "hybrid" in combined else "onsite")

            jobs.append(Job(
                title=title,
                company=name,
                url=url,
                date_posted=date_iso,
                location=location,
                source="workday",
                work_mode=work_mode,
                jd_text="",
            ))
        except Exception as exc:
            logger.debug("Workday[%s] skipping malformed job: %s", name, exc)

    logger.info("Workday[%s] fetched %d jobs", name, len(jobs))
    return jobs
