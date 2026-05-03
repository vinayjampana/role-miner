"""Generic Playwright-based scraper for custom career sites.

Two strategies:
1. scrape_json_api: for sites where we discovered a proprietary JSON API
   in JS chunks (e.g. Cars24's /api/v1/joblist/job-filter). Paginates
   automatically. Zero LLM cost.
2. scrape: Playwright fallback for sites with no discoverable API.
   Renders page, handles pagination, extracts job cards from DOM.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)

_TIMEOUT_MS = 25_000
_IDLE_WAIT_MS = 6_000
_MAX_PAGINATION_CLICKS = 10
_PAGE_STABLE_MS = 2_000

_LOCATION_RE = re.compile(
    r"(?:bangalore|bengaluru|mumbai|hyderabad|chennai|gurgaon|gurugram|"
    r"pune|noida|delhi|kolkata|ahmedabad|india|remote|hybrid|onsite)",
    re.IGNORECASE,
)

_PAGINATION_SELECTORS = [
    "button:has-text('Load More')",
    "button:has-text('Show More')",
    "button:has-text('See More')",
    "button:has-text('View More')",
    "a:has-text('Load More')",
    "a:has-text('Next')",
    "button[aria-label*='next' i]",
    "button[aria-label*='load more' i]",
    "li.next > a",
    "li.next > button",
    "a[rel='next']",
    "button.pagination-next",
    "a.pagination-next",
]

_JOB_CARD_SELECTORS = [
    "[class*='job-card' i]",
    "[class*='jobcard' i]",
    "[class*='job_card' i]",
    "[class*='job-item' i]",
    "[class*='jobitem' i]",
    "[class*='opening' i]",
    "[class*='position' i]",
    "[class*='listing' i]",
    "[class*='vacancy' i]",
    "[data-testid*='job' i]",
    "[class*='career' i][class*='card' i]",
    ".job",
    "li.job",
    "article.job",
    "tr.job",
]


def _detect_work_mode(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"


# ---------------------------------------------------------------------------
# Strategy 1: JSON API scraper (discovered from JS chunks)
# ---------------------------------------------------------------------------

_JOB_TITLE_KEYS = [
    "title", "name", "requisitionTitle", "designation",
    "positionTitle", "jobTitle", "requisition_title",
]
_JOB_LOCATION_KEYS = [
    "location", "city", "officeLocationNames", "locationName",
    "place", "state", "locations",
]
_JOB_URL_KEYS = [
    "url", "href", "link", "absolute_url", "applyUrl", "jobUrl",
    "jd_url", "application_url",
]
# Many proprietary job APIs cap page size (e.g. Cars24 uses 12). Using a small
# POST size avoids stopping early when the server ignores larger requested sizes.
_POST_PAGE_SIZE = 12
_GET_PAGE_SIZE = 50
_MAX_PAGES = 40


async def scrape_json_api(
    api_url: str,
    session: httpx.AsyncClient,
    company_name: str = "",
) -> list[Job]:
    if not api_url or not api_url.strip():
        return []

    base = api_url.strip()
    logger.info("[custom-api] start base=%s company=%s", base, company_name)

    headers = {
        "Accept": "application/json",
    }
    host = (urlparse(base).netloc or "").lower()
    if "cars24.team" in host:
        headers["Origin"] = "https://careers.cars24.com"
        headers["Referer"] = "https://careers.cars24.com/"

    all_jobs: list[Job] = []

    # Try POST first (like Cars24), then GET as fallback
    for method in ("POST", "GET"):
        jobs = await _paginate_api(base, session, headers, company_name, method)
        if jobs:
            return jobs

    return all_jobs


def _synthesize_listing_url(src: dict, api_base: str) -> str | None:
    """When JSON has no job URL, build a stable listing link for known APIs."""
    rid = src.get("requisitionId") or src.get("id")
    if rid is None or str(rid).strip() == "":
        return None
    host = (urlparse(api_base).netloc or "").lower()
    if "cars24" in host:
        return f"https://careers.cars24.com/{rid}"
    return None


def _response_total_cap(data) -> int | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    total = meta.get("total")
    if isinstance(total, dict) and isinstance(total.get("value"), int):
        return total["value"]
    if isinstance(total, int):
        return total
    return None


async def _paginate_api(
    base: str,
    session: httpx.AsyncClient,
    headers: dict,
    company_name: str,
    method: str,
) -> list[Job]:
    all_jobs: list[Job] = []
    seen_ids: set[str] = set()
    page_size = _POST_PAGE_SIZE if method == "POST" else _GET_PAGE_SIZE
    total_cap: int | None = None

    for page in range(1, _MAX_PAGES + 1):
        try:
            if method == "POST":
                body = {"page": page, "size": page_size, "jobType": "normal", "search": ""}
                r = await session.post(base, json=body, headers=headers, timeout=20.0)
            else:
                sep = "&" if "?" in base else "?"
                r = await session.get(
                    f"{base}{sep}page={page}&size={page_size}",
                    headers=headers,
                    timeout=20.0,
                )

            if r.status_code >= 400:
                if page == 1:
                    continue
                break

            data = r.json()
            if page == 1 and total_cap is None:
                total_cap = _response_total_cap(data)
                if total_cap is not None:
                    logger.info("[custom-api] meta total=%s", total_cap)

            items = _extract_job_items(data)
            if not items:
                if page == 1:
                    continue
                break

            new_jobs = 0
            for item in items:
                src = item.get("_source", item)
                item_id = str(src.get("id") or src.get("requisitionId") or src.get("slug", ""))
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)

                title = _pluck(src, _JOB_TITLE_KEYS)
                if not title or len(title) < 3:
                    continue

                location = _pluck_location(src)
                job_url = _pluck(src, _JOB_URL_KEYS)
                if not job_url or not str(job_url).startswith("http"):
                    syn = _synthesize_listing_url(src, base)
                    job_url = syn or job_url or base
                work_mode = _detect_work_mode(f"{title} {location}")

                all_jobs.append(Job(
                    title=_clean_title(title),
                    company=company_name,
                    url=job_url if str(job_url).startswith("http") else urljoin(base, str(job_url)),
                    date_posted=datetime.now(tz=timezone.utc).isoformat(),
                    location=location,
                    source="custom_api",
                    work_mode=work_mode,
                    jd_text="",
                ))
                new_jobs += 1

            logger.info("[custom-api] page=%d items=%d new=%d total=%d", page, len(items), new_jobs, len(all_jobs))

            if total_cap is not None and len(all_jobs) >= total_cap:
                break
            if len(items) < page_size:
                break
            if new_jobs == 0:
                break
        except Exception as exc:
            logger.warning("[custom-api] page=%d error: %s", page, exc)
            if page == 1:
                continue
            break

    if all_jobs:
        logger.info("[custom-api] done company=%s total=%d", company_name, len(all_jobs))
    return all_jobs


def _extract_job_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "jobs", "results", "items", "records", "hits"):
        val = data.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for inner_key in ("data", "jobs", "results", "items", "records", "hits"):
                inner = val.get(inner_key)
                if isinstance(inner, list):
                    return inner
    return []


def _pluck(d: dict, keys: list[str]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and len(v.strip()) > 2:
            return v.strip()
    return ""


def _pluck_location(d: dict) -> str:
    for k in _JOB_LOCATION_KEYS:
        v = d.get(k)
        if isinstance(v, str) and len(v.strip()) > 1:
            return v.strip()
        if isinstance(v, list) and v:
            return ", ".join(str(x) for x in v if isinstance(x, str))
        if isinstance(v, dict):
            name = v.get("name") or v.get("city") or ""
            if name:
                return str(name).strip()
    return ""


def _jobs_from_api_items(items: list[dict], base_url: str, company_name: str) -> list[Job]:
    """Convert raw API job dicts → Job objects. Applies _looks_like_job_title filter."""
    jobs: list[Job] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _pluck(item, _JOB_TITLE_KEYS)
        if not title or not _looks_like_job_title(title):
            continue
        location = _pluck_location(item)
        job_url = _pluck(item, _JOB_URL_KEYS) or base_url
        if job_url and not job_url.startswith("http"):
            job_url = urljoin(base_url, job_url)
        if job_url in seen:
            continue
        seen.add(job_url)
        jobs.append(Job(
            title=_clean_title(title),
            company=company_name,
            url=job_url,
            date_posted=datetime.now(tz=timezone.utc).isoformat(),
            location=location,
            source="custom",
            work_mode=_detect_work_mode(f"{title} {location}"),
            jd_text="",
        ))
    return jobs


def _jobs_from_turbohire_response(
    data: dict | list, api_url: str, company_name: str, *, careers_page_url: str = ""
) -> list[Job]:
    if not isinstance(data, dict):
        return []
    results = data.get("Result")
    if not isinstance(results, list) or not results:
        return []
    if not isinstance(results[0], dict) or "JobId" not in results[0]:
        return []

    org_id = ""
    first = results[0]
    org_details = first.get("OrgDetails")
    if isinstance(org_details, dict):
        org_id = org_details.get("OrgID", "")

    if careers_page_url and "turbohire.co" in careers_page_url:
        p = urlparse(careers_page_url)
        base_careers = f"{p.scheme}://{p.netloc}"
    else:
        parsed = urlparse(api_url)
        base_careers = f"{parsed.scheme}://{parsed.netloc}"

    jobs: list[Job] = []
    seen: set[str] = set()
    for item in results:
        job_id = item.get("JobIdObfuscated") or item.get("JobId", "")
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)

        title = item.get("JobTitle", "")
        if not title or not _looks_like_job_title(title):
            continue

        location_raw = item.get("Location", "[]")
        location = ""
        try:
            import json as _json
            loc_list = _json.loads(location_raw) if isinstance(location_raw, str) else location_raw
            if isinstance(loc_list, list) and loc_list:
                addresses = []
                for loc_item in loc_list:
                    if isinstance(loc_item, dict):
                        addresses.append(loc_item.get("Address", ""))
                    elif isinstance(loc_item, str):
                        addresses.append(loc_item)
                location = ", ".join(a for a in addresses if a)
        except Exception:
            location = str(location_raw)

        if org_id:
            job_url = f"{base_careers}/jobdetailsv2/{job_id}?orgId={org_id}"
        else:
            job_url = api_url

        work_mode = _detect_work_mode(f"{title} {location}")

        jobs.append(Job(
            title=_clean_title(title),
            company=company_name,
            url=job_url,
            date_posted=item.get("PublishedDate", ""),
            location=location,
            source="custom",
            work_mode=work_mode,
            jd_text="",
        ))

    if jobs:
        logger.info("[turbohire] parsed %d jobs from %d results", len(jobs), len(results))
    return jobs


async def scrape(careers_url: str, company_name: str = "") -> list[Job]:
    if not careers_url or not careers_url.strip():
        return []

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("[custom-scrape] playwright not installed — skipping")
        return []

    url = careers_url.strip()
    logger.info("[custom-scrape] start url=%s company=%s", url, company_name)

    from urllib.parse import urlparse as _urlparse
    _input_domain = ".".join(_urlparse(url).netloc.lower().split(".")[-2:])

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True,
            )
            page = await ctx.new_page()

            _ATS_BACKEND_DOMAINS = [
                "azurewebsites.net",
                "turbohire.co",
            ]

            _captured_api_data: list[tuple[str, dict | list]] = []
            _captured_api_urls: list[str] = []

            def _on_response(response):
                if response.status >= 400:
                    return
                ct = (response.headers.get("content-type") or "").lower()
                if "json" not in ct:
                    return
                resp_host = _urlparse(response.url).netloc.lower()
                resp_url_lower = response.url.lower()
                if any(x in resp_url_lower for x in [
                    ".js", ".css", ".map", "/analytics", "/tracking",
                    "/metrics", "/telemetry", "/log", "/pixel",
                    "/token/", "/verifieddomains", "/policydetails",
                    "/publicorganizations", "/clientele", "/departments",
                ]):
                    return
                allowed = (
                    resp_host.endswith(_input_domain)
                    or any(resp_host.endswith(d) for d in _ATS_BACKEND_DOMAINS)
                )
                if not allowed:
                    return
                _captured_api_urls.append(response.url)
                try:
                    import asyncio as _aio
                    task = _aio.ensure_future(response.json())
                    _captured_api_data.append((response.url, task))
                except Exception:
                    pass

            page.on("response", _on_response)

            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=_IDLE_WAIT_MS)
                except PWTimeout:
                    pass
            except PWTimeout:
                logger.warning("[custom-scrape] page load timed out url=%s", url)
                return []

            final_url = page.url
            logger.info(
                "[custom-scrape] page loaded final_url=%s captured_api_urls=%d",
                final_url, len(_captured_api_urls),
            )

            if _captured_api_data:
                for api_url, task in _captured_api_data:
                    try:
                        data = await task
                        jobs = _jobs_from_turbohire_response(data, api_url, company_name, careers_page_url=url)
                        if jobs:
                            logger.info(
                                "[custom-scrape] %d jobs via response-capture api_url=%s",
                                len(jobs), api_url,
                            )
                            return jobs
                        items = _extract_job_items(data)
                        if not items:
                            continue
                        jobs = _jobs_from_api_items(items, api_url, company_name)
                        if jobs:
                            logger.info(
                                "[custom-scrape] %d jobs via response-capture api_url=%s",
                                len(jobs), api_url,
                            )
                            return jobs
                    except Exception as exc:
                        logger.debug("[custom-scrape] response-capture failed %s: %s", api_url, exc)

            if _captured_api_urls:
                for api_url in _captured_api_urls:
                    try:
                        api_resp = await page.request.get(api_url)
                        if not api_resp.ok:
                            continue
                        data = await api_resp.json()
                        items = _extract_job_items(data)
                        if not items:
                            continue
                        jobs = _jobs_from_api_items(items, api_url, company_name)
                        if jobs:
                            logger.info(
                                "[custom-scrape] %d jobs via network-intercept api_url=%s",
                                len(jobs), api_url,
                            )
                            return jobs
                    except Exception as exc:
                        logger.debug("[custom-scrape] network-intercept fetch failed %s: %s", api_url, exc)

            # Try embedded JSON next (Next.js __NEXT_DATA__, ld+json)
            json_jobs = await _extract_from_json(page, final_url, company_name)
            if json_jobs:
                logger.info("[custom-scrape] found %d jobs via embedded JSON", len(json_jobs))
                return json_jobs

            # Click through pagination to load all jobs into DOM
            clicks = await _paginate(page)
            logger.info("[custom-scrape] pagination clicks=%d", clicks)

            # Strategy 1: job card elements
            job_cards = await _extract_job_cards(page, final_url, company_name)
            if job_cards:
                logger.info("[custom-scrape] found %d jobs via card heuristics", len(job_cards))
                return job_cards

            # Strategy 2: links that look like job detail pages
            job_links = await _extract_job_links(page, final_url, company_name)
            if job_links:
                logger.info("[custom-scrape] found %d jobs via links", len(job_links))
                return job_links

            logger.info("[custom-scrape] no jobs found on page")
            return []
        finally:
            await browser.close()


async def _paginate(page) -> int:
    clicks = 0
    for _ in range(_MAX_PAGINATION_CLICKS):
        clicked = False
        for sel in _PAGINATION_SELECTORS:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    prev_html = await page.content()
                    await loc.first.click(timeout=5_000)
                    await page.wait_for_timeout(_PAGE_STABLE_MS)
                    new_html = await page.content()
                    if len(new_html) > len(prev_html) + 50:
                        clicks += 1
                        clicked = True
                        logger.debug("[custom-scrape] pagination click via %s", sel)
                        break
                    else:
                        return clicks
            except Exception:
                continue
        if not clicked:
            break
    return clicks


async def _extract_job_links(page, base_url: str, company_name: str) -> list[Job]:
    links = await page.eval_on_selector_all(
        "a[href]",
        """els => els.map(e => ({
            href: e.href,
            text: (e.textContent || '').trim(),
            parentText: (e.parentElement?.textContent || '').trim().substring(0, 500)
        })).filter(e => e.text.length > 3 && e.text.length < 300)""",
    )

    jobs: list[Job] = []
    seen_urls: set[str] = set()

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").strip()
        parent_text = link.get("parentText", "")

        if not _looks_like_job_title(text):
            continue

        full_href = href
        if full_href.startswith("/"):
            from urllib.parse import urljoin
            full_href = urljoin(base_url, href)

        if full_href in seen_urls:
            continue
        seen_urls.add(full_href)

        location = _extract_location(f"{text} {parent_text}")
        work_mode = _detect_work_mode(f"{text} {parent_text}")

        jobs.append(Job(
            title=_clean_title(text),
            company=company_name,
            url=full_href,
            date_posted=datetime.now(tz=timezone.utc).isoformat(),
            location=location,
            source="custom",
            work_mode=work_mode,
            jd_text=parent_text[:1000],
        ))

    return jobs


async def _extract_job_cards(page, base_url: str, company_name: str) -> list[Job]:
    for sel in _JOB_CARD_SELECTORS:
        try:
            count = await page.locator(sel).count()
            if count == 0:
                continue

            cards = await page.eval_on_selector_all(
                sel,
                """els => els.map(e => {
                    const a = e.querySelector('a[href]');
                    return {
                        text: (e.textContent || '').trim().substring(0, 500),
                        href: a ? a.href : null
                    };
                }).filter(e => e.text.length > 10)""",
            )

            if not cards:
                continue

            jobs: list[Job] = []
            seen: set[str] = set()
            for card in cards:
                text = card.get("text", "")
                href = card.get("href")

                title = _extract_title_from_text(text)
                if not title:
                    continue

                if href and href in seen:
                    continue
                if href:
                    seen.add(href)

                location = _extract_location(text)
                work_mode = _detect_work_mode(text)

                jobs.append(Job(
                    title=title,
                    company=company_name,
                    url=href or base_url,
                    date_posted=datetime.now(tz=timezone.utc).isoformat(),
                    location=location,
                    source="custom",
                    work_mode=work_mode,
                    jd_text=text[:1000],
                ))

            if jobs:
                return jobs
        except Exception as exc:
            logger.debug("[custom-scrape] selector %s failed: %s", sel, exc)
            continue

    return []


async def _extract_from_json(page, base_url: str, company_name: str) -> list[Job]:
    import json as _json

    next_data = await page.eval_on_selector_all(
        'script#__NEXT_DATA__',
        "els => els.map(e => e.textContent)",
    )
    for raw in next_data:
        try:
            data = _json.loads(raw)
            jobs = _walk_json_for_jobs(data, base_url, company_name)
            if jobs:
                return jobs
        except Exception:
            continue

    json_scripts = await page.eval_on_selector_all(
        'script[type="application/json"], script[type="application/ld+json"]',
        "els => els.map(e => e.textContent).filter(t => t.length > 50)",
    )
    for raw in json_scripts:
        try:
            data = _json.loads(raw)
            jobs = _walk_json_for_jobs(data, base_url, company_name)
            if jobs:
                return jobs
        except Exception:
            continue

    return []


def _walk_json_for_jobs(data, base_url: str, company_name: str, depth: int = 0) -> list[Job]:
    if depth > 5:
        return []
    if isinstance(data, list):
        results: list[Job] = []
        for item in data:
            results.extend(_walk_json_for_jobs(item, base_url, company_name, depth + 1))
        return results
    if not isinstance(data, dict):
        return []

    title_keys = {"title", "name", "requisitionTitle", "designation", "positionTitle", "jobTitle"}
    loc_keys = {"location", "city", "officeLocationNames", "locationName", "place", "state"}
    url_keys = {"url", "href", "link", "absolute_url", "applyUrl", "jobUrl"}

    title = None
    for k in title_keys:
        v = data.get(k)
        if isinstance(v, str) and len(v) > 3:
            title = v
            break

    if not title or not _looks_like_job_title(title):
        # No recognisable job title — recurse into child values before giving up
        for item in data.values():
            results = _walk_json_for_jobs(item, base_url, company_name, depth + 1)
            if results:
                return results
        return []

    location = ""
    for k in loc_keys:
        v = data.get(k)
        if isinstance(v, str) and len(v) > 1:
            location = v
            break
        if isinstance(v, list) and v:
            location = ", ".join(str(x) for x in v if isinstance(x, str))
            break
        if isinstance(v, dict):
            name = v.get("name") or v.get("city")
            if isinstance(name, str):
                location = name
                break

    job_url = base_url
    for k in url_keys:
        v = data.get(k)
        if isinstance(v, str) and v.startswith("http"):
            job_url = v
            break

    return [Job(
        title=_clean_title(title),
        company=company_name,
        url=job_url,
        date_posted=datetime.now(tz=timezone.utc).isoformat(),
        location=location,
        source="custom",
        work_mode=_detect_work_mode(f"{title} {location}"),
        jd_text="",
    )]


_TITLE_BLACKLIST = re.compile(
    r"^(?:home|about|careers?|jobs?|contact|login|sign|apply now|"
    r"see all|view all|show all|back|next|previous|filter|search|"
    r"menu|close|open|read more|learn more|cookie|privacy|terms)",
    re.IGNORECASE,
)

# Whole-word job keyword matching. Excludes ambiguous single words (product, data,
# sales, marketing) that also appear in nav/marketing copy — those require a qualifier.
_JOB_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"engineer(?:ing)?"
    r"|developer|programmer"
    r"|manager"
    r"|analyst"
    r"|designer"
    r"|director"
    r"|lead"
    r"|senior|sr\b"
    r"|junior|jr\b"
    r"|associate"
    r"|intern(?:ship)?"
    r"|head\s+of"
    r"|vp\b"
    r"|chief\b"
    r"|executive"
    r"|consultant"
    r"|specialist"
    r"|architect"
    r"|scientist"
    r"|software"
    r"|frontend|back[\-\s]?end|full[\-\s]?stack"
    r"|devops|sre\b"
    r"|qa\b|tester?"
    r"|sde\b"
    r"|staff"
    r"|principal"
    r"|officer"
    r"|recruiter"
    r")\b",
    re.IGNORECASE,
)

# Marketing/testimonial phrases that indicate the text is NOT a job title.
_MARKETING_RE = re.compile(
    r"\b(?:learn\s+more|talk\s+to|call\s+us|get\s+started|sign\s+up|"
    r"watch\s+(?:now|video)|discover|accelerate|unlock|resolve[sd]?|"
    r"enable[sd]?|increase[sd]?|track\s+usage|analyze|identify|optimize|"
    r"platform|solution[s]?|productivity|workflow[s]?|guidance|support\s+question|"
    r"resolved\s+\d|increase\s+their|learn\s+how|see\s+how)\b",
    re.IGNORECASE,
)

# Job keyword followed by a content-category noun = section heading, not a job title.
# e.g. "Analyst Reports", "Engineer Blog", "Developer Hub"
_CONTENT_SUFFIX_RE = re.compile(
    r"\b(?:reports?|blogs?|hubs?|portals?|tools?|templates?|guides?|resources?|"
    r"updates?|newsletters?|programs?|communities?|events?|webinars?|awards?|"
    r"forums?|councils?|partnerships?|alliances?)\s*$",
    re.IGNORECASE,
)


def _looks_like_job_title(text: str) -> bool:
    text = text.strip()
    word_count = len(text.split())
    if len(text) < 5 or len(text) > 150:
        return False
    if word_count > 10:
        return False
    if _TITLE_BLACKLIST.match(text):
        return False
    if text.lower().startswith("http"):
        return False
    if _MARKETING_RE.search(text):
        return False
    if _CONTENT_SUFFIX_RE.search(text):
        return False
    return bool(_JOB_KEYWORD_RE.search(text))


def _clean_title(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > 150:
        text = text[:150]
    return text


def _extract_title_from_text(text: str) -> str | None:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        if _looks_like_job_title(line):
            return _clean_title(line)
    return None


def _extract_location(text: str) -> str:
    m = _LOCATION_RE.search(text)
    return m.group(0).strip() if m else ""
