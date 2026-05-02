"""Rule-based job filter — India-specific pipeline."""
import re
import logging
from datetime import datetime, timezone

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

ESOP_PATTERNS = [r"\besop\b", r"\bequity\b", r"\bstock options\b", r"\brsus?\b"]

# City aliases — Greenhouse/Lever often use official names that differ from common ones
_LOCATION_ALIASES: dict[str, str] = {
    "bengaluru": "bangalore",
    "bengaluru-vtp": "bangalore",
    "new delhi": "ncr",
    "delhi": "ncr",
    "gurgaon": "ncr",
    "gurugram": "ncr",
    "noida": "ncr",
    "mumbai": "mumbai",
    "bombay": "mumbai",
}

def _normalize_location(loc: str) -> str:
    """Map ATS location strings to canonical city names used in profile."""
    lower = loc.lower()
    for alias, canonical in _LOCATION_ALIASES.items():
        if alias in lower:
            lower = lower.replace(alias, canonical)
    return lower

_IMMEDIATE_PATTERNS = [
    r"\bimmediate\s+joiner\b",
    r"\bimmediate\s+join\b",
    r"\bimmediate\s+joining\b",
    r"\bjoin\s+immediately\b",
    r"\bno\s+notice\s+period\b",
]


def detect_esop(jd_text: str) -> bool:
    """Return True if the JD text mentions equity / ESOP."""
    for pattern in ESOP_PATTERNS:
        if re.search(pattern, jd_text, re.IGNORECASE):
            return True
    return False


def detect_notice_compatible(jd_text: str, notice_days: int) -> bool:
    """
    Return False only if the JD explicitly demands immediate joining AND
    the candidate has a non-zero notice period.

    If notice_days == 0, candidate can join immediately → always compatible.
    """
    if notice_days <= 0:
        return True
    for pattern in _IMMEDIATE_PATTERNS:
        if re.search(pattern, jd_text, re.IGNORECASE):
            return False
    return True


def detect_work_mode(title: str, jd_text: str, location: str) -> str:
    """Detect work mode from job title, JD, and location string."""
    combined = f"{title} {jd_text} {location}".lower()
    if "remote" in combined:
        return "remote"
    if "hybrid" in combined:
        return "hybrid"
    return "onsite"


def parse_date(date_str: str) -> datetime:
    """
    Parse an ISO 8601 string into a timezone-aware datetime.
    Raises ValueError on failure.
    """
    if not date_str:
        raise ValueError("empty date string")

    # Handle timezone offset formats: strip trailing 'Z' / '+00:00'
    clean = date_str.strip()

    # Try direct fromisoformat first (Python 3.11+ handles 'Z')
    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # Try replacing trailing Z
    if clean.endswith("Z"):
        try:
            dt = datetime.fromisoformat(clean[:-1])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Try common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {date_str!r}")


def days_since(date_str: str) -> float:
    """
    Return the number of days since date_str.
    Returns 999 on parse failure (causes the job to be filtered out).
    """
    try:
        dt = parse_date(date_str)
        now = datetime.now(tz=timezone.utc)
        delta = now - dt
        return delta.total_seconds() / 86400
    except Exception:
        return 999.0


def filter_jobs(jobs: list[Job], profile: dict) -> list[Job]:
    """
    Apply rule-based filters and enrich job fields (esop, notice_compatible).

    Filter rules:
    1. Freshness: posted within last 7 days
    2. Location: any profile location matches (case-insensitive) OR remote job+profile
    3. Salary: if known, max must be >= profile salary_min_lpa
    4. Company type: if profile excludes services, filter out service companies
    5. Blocklist: company name not in exclude_companies

    Also sets job.has_esop and job.notice_compatible in-place.
    """
    salary_min = profile.get("salary_min_lpa", 0)
    profile_locations: list[str] = [loc.lower() for loc in profile.get("locations", [])]
    profile_work_modes: list[str] = [m.lower() for m in profile.get("work_mode", [])]
    profile_company_types: list[str] = [ct.lower() for ct in profile.get("company_type", [])]
    exclude_companies: list[str] = [c.lower() for c in profile.get("exclude_companies", [])]
    notice_days: int = profile.get("notice_days", 0)

    passed: list[Job] = []

    for job in jobs:
        # Enrich: ESOP and notice compatibility (in-place)
        job.has_esop = detect_esop(job.jd_text)
        job.notice_compatible = detect_notice_compatible(job.jd_text, notice_days)

        # --- Rule 1: Freshness ---
        # 30 days: ATS boards don't re-timestamp jobs weekly; 7d kills too much
        age = days_since(job.date_posted)
        if age > 30:
            logger.debug("Filtered (stale %.1f days): %s @ %s", age, job.title, job.company)
            continue

        # --- Rule 2: Location ---
        job_loc_lower = _normalize_location(job.location)
        work_mode_lower = job.work_mode.lower()

        location_match = any(loc in job_loc_lower for loc in profile_locations if loc)
        remote_match = (
            "remote" in work_mode_lower
            and "remote" in profile_work_modes
        )
        if not location_match and not remote_match:
            logger.debug("Filtered (location mismatch '%s'): %s @ %s", job.location, job.title, job.company)
            continue

        # --- Rule 3: Salary ---
        if job.salary_lpa is not None:
            sal_max = job.salary_lpa.get("max")
            if sal_max is not None and sal_max < salary_min:
                logger.debug("Filtered (salary %s < %s LPA): %s @ %s", sal_max, salary_min, job.title, job.company)
                continue

        # --- Rule 4: Company type ---
        if profile_company_types and "service" not in profile_company_types:
            if job.company_type == "service":
                logger.debug("Filtered (service company): %s @ %s", job.title, job.company)
                continue

        # --- Rule 5: Blocklist ---
        if job.company.lower() in exclude_companies:
            logger.debug("Filtered (blocklisted): %s @ %s", job.title, job.company)
            continue

        passed.append(job)

    logger.info("filter_jobs: %d/%d jobs passed", len(passed), len(jobs))
    return passed
