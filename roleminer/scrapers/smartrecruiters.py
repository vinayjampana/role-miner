"""SmartRecruiters ATS — public postings API (no auth)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_API_LIST = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings"
_PAGE_SIZE = 100


def _work_mode(location: dict | None) -> str:
    if not location:
        return "onsite"
    if location.get("remote"):
        return "remote"
    if location.get("hybrid"):
        return "hybrid"
    return "onsite"


def _location_text(location: dict | None) -> str:
    if not location:
        return ""
    full = location.get("fullLocation")
    if isinstance(full, str) and full.strip():
        return full.strip()
    parts = [
        location.get("city"),
        location.get("region"),
        location.get("country"),
    ]
    return ", ".join(str(p) for p in parts if p)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def _fetch(session: httpx.AsyncClient, url: str) -> dict:
    r = await session.get(
        url,
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


async def scrape(identifier: str, session: httpx.AsyncClient, company_name: str = "") -> list[Job]:
    """
    List all public postings for a SmartRecruiters company identifier
    (path segment from careers.smartrecruiters.com/{identifier}).
    """
    ident = (identifier or "").strip()
    if not ident:
        return []

    name = company_name or ident
    path_ident = quote(ident, safe="")
    base = _API_LIST.format(identifier=path_ident)
    jobs: list[Job] = []
    offset = 0

    try:
        while True:
            url = f"{base}?limit={_PAGE_SIZE}&offset={offset}"
            data = await _fetch(session, url)
            items = data.get("content") or []
            total = int(data.get("totalFound") or 0)

            for item in items:
                try:
                    title = (item.get("name") or "").strip()
                    if not title:
                        continue
                    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
                    uuid = item.get("uuid") or ""
                    comp = item.get("company") if isinstance(item.get("company"), dict) else {}
                    cid = (comp.get("identifier") or ident).strip()
                    if uuid and cid:
                        public_url = f"https://jobs.smartrecruiters.com/{cid}/{uuid}"
                    else:
                        public_url = item.get("ref") or ""

                    released = item.get("releasedDate") or ""
                    date_posted = released or datetime.now(tz=timezone.utc).isoformat()

                    jobs.append(Job(
                        title=title,
                        company=name,
                        url=public_url,
                        date_posted=date_posted,
                        location=_location_text(loc),
                        source="smartrecruiters",
                        work_mode=_work_mode(loc),
                        jd_text="",
                    ))
                except Exception as exc:
                    logger.debug("SmartRecruiters[%s] skip row: %s", ident, exc)

            offset += len(items)
            if not items or offset >= total:
                break
    except Exception as exc:
        logger.warning("SmartRecruiters[%s] fetch failed: %s", ident, exc)
        return []

    logger.info("SmartRecruiters[%s] fetched %d jobs", ident, len(jobs))
    return jobs
