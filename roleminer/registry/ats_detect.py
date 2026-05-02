"""Recognise ATS (Greenhouse, Lever, Ashby, Workday) from job or careers URLs."""
from __future__ import annotations

import re
from urllib.parse import unquote

# URLs in HTML (href, iframe src, JSON in script, etc.)
_URL_IN_HTML = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
# Protocol-relative Greenhouse embeds: //boards.greenhouse.io/...
_GREENHOUSE_REL = re.compile(
    r"//((?:job-boards|boards)\.greenhouse\.io/[^\s\"'<>]+)",
    re.IGNORECASE,
)

# Board slug capture for APIs; order = more specific / alternate hosts first.
_GREENHOUSE = re.compile(
    r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_board\?[^#]*\bfor=([^&?#]+)|([^/?#]+))",
    re.IGNORECASE,
)
_GREENHOUSE_API = re.compile(
    r"boards-api\.greenhouse\.io/v1/boards/([^/?#\"'\\]+)",
    re.IGNORECASE,
)
_LEVER = re.compile(r"jobs(?:\.eu)?\.lever\.co/([^/?#]+)", re.IGNORECASE)
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)", re.IGNORECASE)
_SMARTRECRUITERS = re.compile(
    r"(?:careers|jobs)\.smartrecruiters\.com/([^/?#]+)",
    re.IGNORECASE,
)
# Human-facing board URL: {tenant}.wd{N}.myworkdayjobs.com/{board}
# Excludes /en-US/job/... detail pages and /wday/cxs/... API calls (handled separately).
_WORKDAY_HUMAN = re.compile(
    r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?!wday/|en-[A-Z]{2}/)([^/?#\s\"'<>]+)",
    re.IGNORECASE,
)


def workday_human_to_cxs(url: str) -> str | None:
    """
    Convert a human-facing Workday board URL to the CXS JSON API URL.

    https://browserstack.wd3.myworkdayjobs.com/External
    → https://browserstack.wd3.myworkdayjobs.com/wday/cxs/browserstack/External/jobs
    """
    m = _WORKDAY_HUMAN.search(url)
    if not m:
        return None
    tenant, instance, board = m.group(1), m.group(2), m.group(3).split("/")[0]
    return f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs"


def detect_ats_from_url(url: str | None) -> tuple[str, str] | None:
    """
    Return (ats_type, ats_slug) if the URL is a supported ATS.

    Slug is the board/team id for Greenhouse, Lever, and Ashby. Workday uses
    careers_url for scraping; slug is always "" when ats_type is workday.
    """
    if not url or not str(url).strip():
        return None
    u = str(url).strip()

    m = _GREENHOUSE.search(u)
    if m:
        slug = (m.group(1) or m.group(2) or "").strip()
        slug = unquote(slug)
        if slug:
            return ("greenhouse", slug)

    m = _GREENHOUSE_API.search(u)
    if m:
        slug = unquote(m.group(1).strip())
        if slug:
            return ("greenhouse", slug)

    m = _LEVER.search(u)
    if m:
        return ("lever", unquote(m.group(1).strip()))

    m = _ASHBY.search(u)
    if m:
        return ("ashby", unquote(m.group(1).strip()))

    m = _SMARTRECRUITERS.search(u)
    if m:
        slug = unquote(m.group(1).strip())
        if slug:
            return ("smartrecruiters", slug)

    u_lower = u.lower()
    if "myworkdayjobs.com" in u_lower:
        # CXS API endpoint
        if "/wday/cxs/" in u:
            return ("workday", "")
        # Human-facing board URL — recognise but don't convert here
        if _WORKDAY_HUMAN.search(u):
            return ("workday", "")

    return None


def _normalize_url_candidate(raw: str) -> str:
    # Strip trailing punctuation and HTML entity fragments
    raw = raw.rstrip(".,;)'\\]}>")
    # Truncate at HTML entity start (&quot; &amp; etc.)
    for marker in ("&quot;", "&amp;", "&lt;", "&gt;", "&#"):
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[:idx]
    return raw.rstrip(".,;)'\\]}>")


def find_embedded_ats_url(html: str | None) -> str | None:
    """
    Find the first ATS job-board URL embedded in HTML.

    Corporate /careers pages often stay on the company domain but reference
    Greenhouse, Lever, Ashby, or Workday cxs APIs in iframes, links, or scripts.
    """
    if not html:
        return None
    for m in _URL_IN_HTML.finditer(html):
        candidate = _normalize_url_candidate(m.group(0))
        if detect_ats_from_url(candidate):
            return candidate
    for m in _GREENHOUSE_REL.finditer(html):
        candidate = _normalize_url_candidate("https://" + m.group(1))
        if detect_ats_from_url(candidate):
            return candidate
    return None
