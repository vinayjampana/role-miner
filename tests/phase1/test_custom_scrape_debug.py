"""
Debug test: trace _scrape_company for a custom-ATS company (Razorpay).

Covers the full resolve → dispatch path with verbose logging so we can
see exactly where custom career sites fail.

Run:  pytest tests/phase1/test_custom_scrape_debug.py -v -s
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from roleminer.registry.ats_detect import (
    detect_ats_from_url,
    find_embedded_ats_url,
    workday_human_to_cxs,
)
from roleminer.registry.browser_detect import detect_ats_with_browser
from roleminer.registry.db import insert_company, init_db, update_company_fields
from roleminer.scrapers import greenhouse, lever, ashby, workday, cutshort
from roleminer.scrapers.base import Job, make_session

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-5s %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger("test_custom_scrape")


RAZORPAY = {
    "name": "Razorpay",
    "domain": "razorpay.com",
    "ats_type": "custom",
    "hq_city": "Bangalore",
    "company_type": "product",
    "funding_stage": "Series F",
}

RAZORPAY_CAREERS = "https://razorpay.com/careers/"


async def _resolve_careers_to_ats_url(session, careers_url: str) -> tuple[str, tuple[str, str] | None]:
    u = (careers_url or "").strip()
    if not u:
        logger.info("[careers-resolve] empty input — skip")
        return u, None
    logger.info("[careers-resolve] step=fetch url=%s", u)
    try:
        r = await session.get(u, follow_redirects=True, timeout=25.0)
        final = str(r.url)
        logger.info(
            "[careers-resolve] step=http status=%s final_url=%s (redirected=%s)",
            r.status_code,
            final,
            "yes" if final.rstrip("/") != u.rstrip("/") else "no",
        )
        if r.status_code >= 400:
            det = detect_ats_from_url(u)
            logger.info("[careers-resolve] step=detect(bad_status) on original url → %s", det)
            return u, det
        det = detect_ats_from_url(final)
        logger.info("[careers-resolve] step=detect(final_url) → %s", det)
        if det:
            canonical = workday_human_to_cxs(final) or final if det[0] == "workday" else final
            return canonical, det
        html_len = len(r.text or "")
        logger.info("[careers-resolve] step=html_scan body_bytes=%s (no ATS in location bar)", html_len)
        embedded = find_embedded_ats_url(r.text)
        if embedded:
            det2 = detect_ats_from_url(embedded)
            canonical2 = workday_human_to_cxs(embedded) or embedded if det2 and det2[0] == "workday" else embedded
            logger.info("[careers-resolve] step=embedded found=%s detect → %s", canonical2, det2)
            return canonical2, det2
        logger.info("[careers-resolve] step=embedded none — trying browser render")
    except Exception as exc:
        logger.warning("[careers-resolve] step=error %s — trying browser render", exc)

    try:
        browser_url, browser_det = await detect_ats_with_browser(u)
        logger.info("[careers-resolve] step=browser_detect → %s url=%s", browser_det, browser_url)
        return browser_url, browser_det
    except Exception as exc:
        logger.warning("[careers-resolve] step=browser_detect error: %s", exc)
        return u, None


async def _scrape_company(
    company: dict,
    session,
    profile: dict,
    conn: sqlite3.Connection | None = None,
) -> list[Job]:
    ats_type = (company.get("ats_type") or "").strip()
    slug = (company.get("ats_slug") or "").strip()
    name = company.get("name", "")
    careers_url = (company.get("careers_url") or "").strip()
    cid = company.get("id")

    logger.info(
        "[scrape] company=%r id=%s initial ats_type=%r ats_slug=%r careers_url=%s",
        name, cid, ats_type, slug, careers_url or "(none)",
    )

    det: tuple[str, str] | None = None
    needs_resolve = bool(
        careers_url
        and (
            ats_type in ("", "custom")
            or (ats_type in ("greenhouse", "lever", "ashby") and not slug)
        )
    )
    if needs_resolve:
        logger.info(
            "[scrape] company=%r step=careers_resolve reason=%s",
            name,
            "custom_or_empty_ats" if ats_type in ("", "custom") else "missing_slug_for_known_ats",
        )
        resolved, det = await _resolve_careers_to_ats_url(session, careers_url)
        if det:
            ats_type, slug = det[0], (det[1] or "").strip()
            careers_url = resolved
        elif resolved != careers_url:
            careers_url = resolved
        logger.info(
            "[scrape] company=%r step=after_resolve ats_type=%r ats_slug=%r careers_url=%s det=%s",
            name, ats_type, slug, careers_url or "(none)", det,
        )
    else:
        logger.info(
            "[scrape] company=%r step=careers_resolve skipped (have slug or no careers_url for resolve)",
            name,
        )

    if conn and cid and det:
        patch: dict = {}
        if ats_type and ats_type != company.get("ats_type"):
            patch["ats_type"] = ats_type
        if slug and slug != (company.get("ats_slug") or ""):
            patch["ats_slug"] = slug
        new_cu = (careers_url or "").strip()
        if new_cu and new_cu != (company.get("careers_url") or "").strip():
            patch["careers_url"] = new_cu
        if patch:
            logger.info("[scrape] company=%r step=db_patch %s", name, patch)
            update_company_fields(conn, cid, patch)
            company.update(patch)
        else:
            logger.info("[scrape] company=%r step=db_patch none (already in sync)", name)
    elif conn and cid and not det:
        logger.info("[scrape] company=%r step=db_patch skipped (no new ATS from resolve)", name)

    if not slug and ats_type not in ("workday", "cutshort"):
        logger.warning(
            "[scrape] company=%r step=abort reason=no_ats_slug ats_type=%r careers_url=%s",
            name, ats_type, careers_url or "(none)",
        )
        return []

    try:
        logger.info("[scrape] company=%r step=call_scraper ats=%r slug=%r", name, ats_type, slug)
        if ats_type == "greenhouse":
            jobs = await greenhouse.scrape(slug, session, company_name=name)
        elif ats_type == "lever":
            jobs = await lever.scrape(slug, session, company_name=name)
        elif ats_type == "ashby":
            jobs = await ashby.scrape(slug, session, company_name=name)
        elif ats_type == "workday":
            jobs = await workday.scrape(careers_url, session, company_name=name)
        elif ats_type == "cutshort":
            skills = profile.get("skills", [])
            locations = profile.get("locations", [])
            jobs = await cutshort.scrape(skills, locations, session)
        else:
            logger.warning("[scrape] company=%r step=abort unknown ats_type=%r", name, ats_type)
            return []
        logger.info("[scrape] company=%r step=done jobs_fetched=%s", name, len(jobs))
        return jobs
    except Exception as exc:
        logger.error("[scrape] company=%r step=error ats=%r slug=%r: %s", name, ats_type, slug, exc)
        return []


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = init_db(path)
    yield conn
    conn.close()


@pytest.fixture
async def session():
    async with make_session() as s:
        yield s


def test_detect_ats_on_razorpay_greenhouse_url():
    url = "https://boards.greenhouse.io/razorpay"
    result = detect_ats_from_url(url)
    print(f"\n[UNIT] detect_ats_from_url({url!r}) -> {result}")
    assert result == ("greenhouse", "razorpay")


def test_detect_ats_on_careers_page_url():
    result = detect_ats_from_url(RAZORPAY_CAREERS)
    print(f"\n[UNIT] detect_ats_from_url({RAZORPAY_CAREERS!r}) -> {result}")
    assert result is None


@pytest.mark.asyncio
async def test_scrape_custom_no_careers_url(db, session):
    cid = insert_company(db, RAZORPAY)
    company = {**RAZORPAY, "id": cid}

    print("\n" + "=" * 70)
    print("TEST 3: _scrape_company — no careers_url (seed state)")
    print("=" * 70)

    jobs = await _scrape_company(company, session, {}, conn=db)

    print(f"\n[RESULT] jobs returned: {len(jobs)}")
    assert jobs == []


@pytest.mark.asyncio
async def test_scrape_custom_with_careers_url(db, session):
    cid = insert_company(db, RAZORPAY)
    company = {**RAZORPAY, "id": cid, "careers_url": RAZORPAY_CAREERS}

    print("\n" + "=" * 70)
    print(f"TEST 4: _scrape_company — with careers_url={RAZORPAY_CAREERS}")
    print("=" * 70)

    jobs = await _scrape_company(company, session, {}, conn=db)

    print(f"\n[RESULT] jobs returned: {len(jobs)}")
    if jobs:
        print(f"[RESULT] sample job: {jobs[0].title} @ {jobs[0].url}")

    row = db.execute(
        "SELECT ats_type, ats_slug, careers_url FROM companies WHERE id = ?",
        (cid,),
    ).fetchone()
    print(f"[DB] after scrape: ats_type={row[0]!r} ats_slug={row[1]!r} careers_url={row[2]!r}")

    if row[0] == "custom":
        print("\n[FAIL] ats_type still 'custom' — resolve did NOT detect the ATS")
    elif row[0] == "greenhouse":
        print(f"\n[PASS] ats_type patched to 'greenhouse', slug={row[1]!r}")
        if not jobs:
            print("[WARN] ATS detected but 0 jobs — greenhouse scraper issue")
        else:
            print(f"[PASS] {len(jobs)} jobs fetched successfully")


@pytest.mark.asyncio
async def test_live_probe_razorpay_careers(session):
    print("\n" + "=" * 70)
    print(f"TEST 5: Live HTTP probe — {RAZORPAY_CAREERS}")
    print("=" * 70)

    r = await session.get(RAZORPAY_CAREERS, follow_redirects=True, timeout=25.0)

    print(f"  status_code   = {r.status_code}")
    print(f"  final_url     = {r.url}")
    print(f"  redirected    = {str(r.url).rstrip('/') != RAZORPAY_CAREERS.rstrip('/')}")
    print(f"  content_type  = {r.headers.get('content-type', '?')}")
    print(f"  body_length   = {len(r.text)} chars")

    det = detect_ats_from_url(str(r.url))
    print(f"  detect_ats(final_url) -> {det}")

    embedded = find_embedded_ats_url(r.text)
    print(f"  find_embedded_ats_url -> {embedded}")

    print(f"\n  --- HTML snippet (first 2000 chars) ---")
    print(r.text[:2000])
    print("  --- end snippet ---")
