"""Role filter — drop non-frontend / non-fullstack engineering roles by title."""
import logging

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

INCLUDE_TITLE_KEYWORDS = [
    "frontend", "front-end", "front end",
    "fullstack", "full-stack", "full stack",
    "software engineer", "software developer", "sde", "swe",
    "react", "ui engineer", "ui developer",
    "web engineer", "web developer",
    "engineer ii", "engineer iii", "senior engineer", "staff engineer",
    "engineering manager",
]

EXCLUDE_TITLE_KEYWORDS = [
    "backend", "back-end", "back end",
    "data scientist", "data engineer", "data analyst", "ml engineer",
    "machine learning", "devops", "infrastructure", "platform",
    "android", "ios", "mobile",
    "qa ", "quality assurance", "test engineer", "sdet",
    "product manager", "program manager", "project manager",
    "recruiter", "hr ", "people",
    "sales", "account executive", "account manager",
    "finance", "legal", "compliance",
    "designer", "ux designer", "ui designer",
    "business analyst",
    "intern",
]


def filter_by_role(jobs: list[Job]) -> tuple[list[Job], list[dict]]:
    """
    Returns (passed_jobs, dropped_records).

    Logic:
    - INCLUDE match → keep (overrides exclude)
    - No include + EXCLUDE match → drop
    - No match at all → keep (conservative)
    """
    passed: list[Job] = []
    dropped: list[dict] = []

    for job in jobs:
        title_lower = job.title.lower()
        included = any(kw in title_lower for kw in INCLUDE_TITLE_KEYWORDS)
        excluded = any(kw in title_lower for kw in EXCLUDE_TITLE_KEYWORDS)

        if included:
            passed.append(job)
        elif excluded:
            dropped.append({
                "title": job.title,
                "company": job.company,
                "reason": "role_mismatch",
            })
        else:
            passed.append(job)

    logger.info("filter_by_role: %d/%d kept, %d dropped", len(passed), len(jobs), len(dropped))
    return passed, dropped
