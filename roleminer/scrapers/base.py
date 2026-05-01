from dataclasses import dataclass, field
from datetime import datetime, timezone
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class Job:
    title: str
    company: str
    url: str
    date_posted: str        # ISO 8601 string
    location: str
    source: str             # greenhouse | lever | ashby | cutshort | ...
    work_mode: str = "onsite"    # remote | hybrid | onsite
    salary_lpa: dict | None = None  # {"min": 30, "max": 50} or None
    jd_text: str = ""
    funding_stage: str = ""
    has_esop: bool = False
    company_type: str = ""   # product | service | consulting
    notice_compatible: bool = True


@dataclass
class ScoredJob:
    title: str
    company: str
    url: str
    date_posted: str
    location: str
    source: str
    work_mode: str = "onsite"
    salary_lpa: dict | None = None
    jd_text: str = ""
    funding_stage: str = ""
    has_esop: bool = False
    company_type: str = ""
    notice_compatible: bool = True
    score: int = 0
    reason: str = ""
    skill_gap: dict = field(default_factory=lambda: {"have": [], "need": [], "gap": []})

    @classmethod
    def from_job(cls, job: Job, score: int = 0, reason: str = "", skill_gap: dict | None = None) -> "ScoredJob":
        return cls(
            title=job.title,
            company=job.company,
            url=job.url,
            date_posted=job.date_posted,
            location=job.location,
            source=job.source,
            work_mode=job.work_mode,
            salary_lpa=job.salary_lpa,
            jd_text=job.jd_text,
            funding_stage=job.funding_stage,
            has_esop=job.has_esop,
            company_type=job.company_type,
            notice_compatible=job.notice_compatible,
            score=score,
            reason=reason,
            skill_gap=skill_gap or {"have": [], "need": [], "gap": []},
        )


def dedup_by_url(jobs: list[Job]) -> list[Job]:
    """Remove duplicate jobs by URL, keeping first occurrence."""
    seen = set()
    result = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            result.append(job)
    return result


def make_session(proxy_url: str = "") -> httpx.AsyncClient:
    """Create an HTTPX async client with optional proxy."""
    kwargs: dict = {
        "timeout": 30.0,
        "headers": {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json",
        },
        "follow_redirects": True,
    }
    if proxy_url:
        kwargs["proxies"] = proxy_url
    return httpx.AsyncClient(**kwargs)


def retry_get(func):
    """Decorator: retry up to 3 times with exponential backoff."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )(func)
