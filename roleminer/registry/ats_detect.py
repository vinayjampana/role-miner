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
_LEVER = re.compile(r"jobs(?:\.eu)?\.lever\.co/([^/?#]+)", re.IGNORECASE)
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)", re.IGNORECASE)


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

    m = _LEVER.search(u)
    if m:
        return ("lever", unquote(m.group(1).strip()))

    m = _ASHBY.search(u)
    if m:
        return ("ashby", unquote(m.group(1).strip()))

    # Tenant JSON API (see registry workday examples), not /en-US/job/... detail pages.
    if "myworkdayjobs.com" in u.lower() and "/wday/cxs/" in u:
        return ("workday", "")

    return None


def _normalize_url_candidate(raw: str) -> str:
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
