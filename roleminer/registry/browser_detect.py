"""Playwright-based ATS detection for JS-rendered career pages.

Used as fallback when static HTML fetch finds no ATS embed.
Renders the page in a headless browser, waits for JS to load,
then scans four signals for recognizable ATS board URLs:
  1. Final URL after JS navigation/redirects
  2. Network requests to known ATS API domains
  3. Fully-rendered DOM (find_embedded_ats_url)
  4. All <a href> links pointing to ATS domains
"""
from __future__ import annotations

import logging
import re

from roleminer.registry.ats_detect import detect_ats_from_url, find_embedded_ats_url, workday_human_to_cxs

logger = logging.getLogger(__name__)

# Matches network requests/hrefs that come from ATS systems.
# Includes both API endpoints and human-facing board URLs.
_ATS_URL_RE = re.compile(
    r"https?://(?:"
    r"(?:job-boards|boards)\.greenhouse\.io/[^\s\"'<>]+"
    r"|jobs(?:\.eu)?\.lever\.co/[^\s\"'<>]+"
    r"|jobs\.ashbyhq\.com/[^\s\"'<>]+"
    r"|(?:careers|jobs)\.smartrecruiters\.com/[^\s\"'<>]+"
    r"|[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[^\s\"'<>]+"
    r")",
    re.IGNORECASE,
)

_TIMEOUT_MS = 20_000
_IDLE_WAIT_MS = 4_000


def _first_ats(urls: list[str]) -> tuple[str, tuple[str, str] | None] | None:
    """Return (canonical_url, det) for first URL that detect_ats_from_url recognises.

    For Workday, converts human-facing board URL to the CXS API URL so the
    caller can store it directly as careers_url.
    """
    for u in urls:
        det = detect_ats_from_url(u)
        if det:
            if det[0] == "workday":
                cxs = workday_human_to_cxs(u) or u
                return cxs, det
            return u, det
    return None


async def detect_ats_with_browser(careers_url: str) -> tuple[str, tuple[str, str] | None]:
    """
    Render careers_url in headless Chromium.
    Returns (ats_url_or_final_url, detect_ats_from_url_result_or_None).
    """
    if not careers_url or not careers_url.strip():
        return careers_url, None

    url = careers_url.strip()
    logger.info("[browser-detect] start url=%s", url)

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("[browser-detect] playwright not installed — skipping")
        return url, None

    captured: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                java_script_enabled=True,
            )
            page = await ctx.new_page()

            def _on_request(request):
                req_url = request.url
                if _ATS_URL_RE.search(req_url):
                    captured.append(req_url)
                    logger.info("[browser-detect] network hit url=%s", req_url)

            page.on("request", _on_request)

            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=_IDLE_WAIT_MS)
                except PWTimeout:
                    pass
            except PWTimeout:
                logger.warning("[browser-detect] page load timed out url=%s", url)

            final_url = page.url
            logger.info("[browser-detect] final_url=%s network_hits=%d", final_url, len(captured))

            # Signal 1: final URL is an ATS board
            det = detect_ats_from_url(final_url)
            if det:
                canonical = final_url
                if det[0] == "workday":
                    canonical = workday_human_to_cxs(final_url) or final_url
                logger.info("[browser-detect] signal=final_url det=%s url=%s", det, canonical)
                return canonical, det

            # Signal 2: network requests to ATS APIs
            hit = _first_ats(captured)
            if hit:
                logger.info("[browser-detect] signal=network det=%s url=%s", hit[1], hit[0])
                return hit

            try:
                html = await page.content()

                # Signal 3: ATS URL in rendered DOM text
                embedded = find_embedded_ats_url(html)
                if embedded:
                    det = detect_ats_from_url(embedded)
                    if det and det[0] == "workday":
                        embedded = workday_human_to_cxs(embedded) or embedded
                    logger.info("[browser-detect] signal=dom_embed embedded=%s det=%s", embedded, det)
                    return embedded, det

                # Signal 4: <a href> links to ATS domains (company links to their board)
                hrefs: list[str] = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.href).filter(h => h.startsWith('http'))",
                )
                ats_hrefs = [h for h in hrefs if _ATS_URL_RE.search(h)]
                logger.info("[browser-detect] signal=hrefs ats_hrefs=%d total_hrefs=%d", len(ats_hrefs), len(hrefs))
                hit = _first_ats(ats_hrefs)
                if hit:
                    logger.info("[browser-detect] signal=href det=%s url=%s", hit[1], hit[0])
                    return hit

                logger.info("[browser-detect] all signals exhausted body_bytes=%d", len(html))
            except Exception as exc:
                logger.warning("[browser-detect] dom/href scan failed: %s", exc)

            return final_url, None

        finally:
            await browser.close()
