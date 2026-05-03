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

# Job portal domains we can't natively scrape but should follow as careers_url.
# Used in Signal 5 (href scan) and find_redirect_via_cta.
_JOB_PORTAL_RE = re.compile(
    r"https?://[a-z0-9.-]*(?:"
    r"hire\.trakstar\.com"
    r"|apply\.workable\.com"
    r"|jobs\.workable\.com"
    r"|\.breezy\.hr"
    r"|\.recruitee\.com"
    r"|app\.recruitee\.com"
    r"|\.icims\.com"
    r"|\.taleo\.net"
    r"|\.bamboohr\.com"
    r"|\.jazzhr\.com"
    r"|\.teamtailor\.com"
    r"|\.pinpointhq\.com"
    r"|\.comeet\.com"
    r"|\.gr8people\.com"
    r"|careers\.zoho\.com"
    r"|\.freshteam\.com"
    r"|\.keka\.com"
    r"|\.darwinbox\.com"
    r"|springrecruit\.com"
    r"|\.dover\.io"
    r"|\.occupop\.com"
    r")/",
    re.IGNORECASE,
)

# CTA link text that likely leads to the actual job listings page.
_CTA_TEXT_RE = re.compile(
    r"(?:view|see|browse|explore|all|open)\s+(?:open\s+)?(?:jobs?|positions?|roles?|openings?)\b"
    r"|current\s+openings?\b"
    r"|open\s+positions?\b"
    r"|(?:apply|join)\s+(?:now|us|today)\b"
    r"|careers?\s+(?:portal|page|at|with)\b"
    r"|\bwork\s+with\s+us\b",
    re.IGNORECASE,
)


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

                # Signal 5: external job portal hrefs (unknown/unsupported ATS systems)
                portal_hrefs = [h for h in hrefs if _JOB_PORTAL_RE.search(h)]
                logger.info(
                    "[browser-detect] signal=portal_hrefs count=%d total_hrefs=%d",
                    len(portal_hrefs),
                    len(hrefs),
                )
                if portal_hrefs:
                    best = portal_hrefs[0]
                    logger.info("[browser-detect] signal=job_portal_href url=%s", best)
                    return best, None

                logger.info("[browser-detect] all signals exhausted body_bytes=%d", len(html))
            except Exception as exc:
                logger.warning("[browser-detect] dom/href scan failed: %s", exc)

            return final_url, None

        finally:
            await browser.close()


async def find_redirect_via_cta(careers_url: str) -> str | None:
    """
    Zero-job fallback: find the real job portal URL from a careers landing page.

    Phase 1 — scan <a href> links filtered by CTA text or portal domain.
    Phase 2 — click <button> elements with CTA text, capture popup/navigation URL.

    Returns external URL if found (different domain from careers_url), else None.
    Updates careers_url in the caller's DB after return.
    """
    url = (careers_url or "").strip()
    if not url:
        return None

    logger.info("[browser-cta] start url=%s", url)

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("[browser-cta] playwright not installed — skipping")
        return None

    from urllib.parse import urlparse

    input_host = urlparse(url).netloc.lower()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                java_script_enabled=True,
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=_IDLE_WAIT_MS)
                except PWTimeout:
                    pass
            except PWTimeout:
                logger.warning("[browser-cta] page load timed out url=%s", url)
                return None

            # Phase 1: <a href> links — no click needed, just extract
            link_data: list[dict] = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({ text: (e.innerText || e.textContent || '').trim(), href: e.href || '' }))",
            )
            for el in link_data:
                text = (el.get("text") or "").strip()
                href = (el.get("href") or "").strip()
                if not href.startswith("http"):
                    continue
                if urlparse(href).netloc.lower() == input_host:
                    continue
                is_cta = bool(_CTA_TEXT_RE.search(text))
                is_portal = bool(_JOB_PORTAL_RE.search(href) or _ATS_URL_RE.search(href))
                if is_cta or is_portal:
                    logger.info(
                        "[browser-cta] phase1 found: text=%r cta=%s portal=%s url=%s",
                        text[:60], is_cta, is_portal, href,
                    )
                    return href

            # Phase 2: <button> click + popup/navigation capture
            btn_data: list[dict] = await page.eval_on_selector_all(
                "button, [role='button']",
                "els => els.map(e => ({ text: (e.innerText || e.textContent || '').trim() }))",
            )
            cta_btn_texts = [
                d["text"] for d in btn_data
                if d.get("text") and _CTA_TEXT_RE.search(d["text"])
            ]
            logger.info("[browser-cta] phase2 cta_buttons=%d", len(cta_btn_texts))

            for btn_text in cta_btn_texts[:3]:  # try up to 3 CTA buttons
                try:
                    async with page.expect_popup(timeout=3000) as popup_info:
                        await page.get_by_text(btn_text, exact=False).first.click(timeout=2000)
                    popup = await popup_info.value
                    popup_url = popup.url
                    await popup.close()
                    if popup_url and popup_url != "about:blank":
                        logger.info("[browser-cta] phase2 popup url=%s text=%r", popup_url, btn_text[:60])
                        return popup_url
                except Exception:
                    pass
                # If no popup, check if page navigated
                try:
                    await page.get_by_text(btn_text, exact=False).first.click(timeout=2000)
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                    new_url = page.url
                    if new_url and urlparse(new_url).netloc.lower() != input_host:
                        logger.info("[browser-cta] phase2 navigation url=%s text=%r", new_url, btn_text[:60])
                        return new_url
                except Exception:
                    pass

            logger.info("[browser-cta] no redirect found url=%s", url)
            return None

        finally:
            await browser.close()
