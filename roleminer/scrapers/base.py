from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
import re as _re
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


def _normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = _re.sub(r"[^\w\s]", " ", t)
    t = _re.sub(r"\biii\b", "3", t)
    t = _re.sub(r"\bii\b", "2", t)
    t = _re.sub(r"\biv\b", "4", t)
    t = _re.sub(r"\bsr\.?\b", "senior", t)
    t = _re.sub(r"\bjr\.?\b", "junior", t)
    return _re.sub(r"\s+", " ", t).strip()


def dedup_fuzzy(jobs: list[Job]) -> list[Job]:
    """Dedup by URL first, then by normalized title+company+location fingerprint."""
    seen_urls: set[str] = set()
    seen_fps: set[str] = set()
    result: list[Job] = []
    for job in jobs:
        if job.url in seen_urls:
            continue
        seen_urls.add(job.url)
        fp = (
            _normalize_title(job.title)
            + "|" + (job.company or "").lower().strip()
            + "|" + (job.location or "").lower().strip()
        )
        if fp in seen_fps:
            continue
        seen_fps.add(fp)
        result.append(job)
    return result


_UA_POOL = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]


def random_ua() -> str:
    return random.choice(_UA_POOL)


def _stealth_headers(ua: str) -> dict[str, str]:
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def make_session(proxy_url: str = "") -> httpx.AsyncClient:
    """Create an HTTPX async client with rotated UA and stealth headers."""
    ua = random_ua()
    kwargs: dict = {
        "timeout": 30.0,
        "headers": _stealth_headers(ua),
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
