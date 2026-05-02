"""Discover proprietary JSON job-list APIs by scanning linked JS bundles."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_JS_SRC_RE = re.compile(r'src=["\']([^"\']+\.js)["\']', re.IGNORECASE)
_JOB_API_CHUNK_LIMIT = 28

_JOB_API_PATTERNS = re.compile(
    r"https?://[^\s\"'<>]+(?:"
    r"/joblist"
    r"|/job-list"
    r"|/jobs/api"
    r"|/api/v[0-9]+/jobs"
    r"|/api/v[0-9]+/openings"
    r"|/api/v[0-9]+/positions"
    r"|/api/v[0-9]+/careers"
    r"|/api/v[0-9]+/listings"
    r")",
    re.IGNORECASE,
)

_TEAM_API_HOST = re.compile(
    r"https://[a-z0-9][a-z0-9.-]*\.[a-z0-9][a-z0-9.-]*\.team\b",
    re.IGNORECASE,
)


def _discover_split_bundle_api(chunk_text: str) -> str | None:
    """
    Some Next/Webpack bundles split the API origin and path across concat().
    If we see a *.team API host and joblist paths in the same file, synthesize
    the filter endpoint (Cars24-style).
    """
    if "job-filter" not in chunk_text and "joblist" not in chunk_text:
        return None
    hosts = _TEAM_API_HOST.findall(chunk_text)
    if not hosts:
        return None
    prefer = [h for h in hosts if "api" in h.lower()]
    pick = prefer[0] if prefer else hosts[0]
    pick = pick.rstrip("/")
    if "joblist/job-filter" in chunk_text or (
        "job-filter" in chunk_text and "joblist" in chunk_text
    ):
        return pick + "/api/v1/joblist/job-filter"
    return None


async def discover_job_api(session, html: str, base_url: str) -> str | None:
    srcs = _JS_SRC_RE.findall(html)[:_JOB_API_CHUNK_LIMIT]
    for src in srcs:
        chunk_url = urljoin(base_url, src)
        try:
            cr = await session.get(chunk_url, follow_redirects=True, timeout=15.0)
            if cr.status_code >= 400:
                continue
            for m in _JOB_API_PATTERNS.finditer(cr.text):
                candidate = m.group(0).rstrip(".,;)'\\]}>")
                logger.info("[discover-job-api] candidate=%s from %s", candidate, src)
                return candidate
            split = _discover_split_bundle_api(cr.text)
            if split:
                logger.info("[discover-job-api] split-bundle=%s from %s", split, src)
                return split
        except Exception:
            continue
    return None


async def discover_job_api_with_alternate_host(
    session, html: str, base_url: str
) -> str | None:
    """Scan JS chunks; if the corporate careers page has no API hints, try careers.{domain}."""
    api = await discover_job_api(session, html, base_url)
    if api:
        return api
    p = urlparse(base_url)
    path_l = (p.path or "").lower()
    netloc_l = (p.netloc or "").lower()
    if "career" not in path_l and "career" not in netloc_l:
        return None
    host = netloc_l
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) < 2:
        return None
    registrable = ".".join(parts[-2:])
    alt_host = f"careers.{registrable}"
    if host == alt_host:
        return None
    alt = f"{p.scheme}://{alt_host}/"
    try:
        r = await session.get(alt, follow_redirects=True, timeout=20.0)
        if r.status_code >= 400:
            return None
        return await discover_job_api(session, r.text, str(r.url))
    except Exception:
        return None
