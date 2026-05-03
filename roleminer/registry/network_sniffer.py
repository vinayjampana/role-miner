"""Playwright network sniffer for career page API discovery.

Boots a headless browser, navigates to the careers URL, intercepts all
JSON responses, and identifies proprietary job APIs by looking for arrays
of objects with job-like keys (title, location, id, url).
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TIMEOUT_MS = 25_000
_IDLE_WAIT_MS = 8_000

_JOB_LIKE_KEYS = {"title", "name", "location", "city", "id", "url", "href", "link"}

_NOISE_EXTENSIONS = re.compile(
    r"\.(js|css|map|woff2?|ttf|eot|png|jpg|jpeg|gif|svg|ico|webp)(\?|$)",
    re.IGNORECASE,
)


def _is_job_api_response(data: object) -> bool:
    if isinstance(data, list) and len(data) >= 2:
        return _items_have_job_keys(data)
    if not isinstance(data, dict):
        return False
    for key in ("data", "jobs", "results", "items", "records", "hits", "job_postings"):
        val = data.get(key)
        if isinstance(val, list) and len(val) >= 2 and _items_have_job_keys(val):
            return True
        if isinstance(val, dict):
            for inner_key in ("data", "jobs", "results", "items", "records", "hits"):
                inner = val.get(inner_key)
                if isinstance(inner, list) and len(inner) >= 2 and _items_have_job_keys(inner):
                    return True
    return False


def _items_have_job_keys(items: list) -> bool:
    if not items:
        return False
    sample = items[:5]
    match_count = 0
    for item in sample:
        if not isinstance(item, dict):
            continue
        keys = {k.lower() for k in item.keys()}
        overlap = keys & _JOB_LIKE_KEYS
        if len(overlap) >= 2:
            match_count += 1
    return match_count >= min(2, len(sample))


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html).strip()
    return html[:50_000]


async def sniff_career_page(url: str) -> dict:
    """Intercept network traffic on a career page and discover job APIs.

    Returns:
        dict with either:
        - {"type": "api", "api_url": ..., "method": ..., "headers": ..., "post_data": ..., "sample": [...]}
        - {"type": "html", "html": "<stripped HTML>"}
    """
    url = (url or "").strip()
    if not url:
        return {"type": "html", "html": ""}

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning("[network-sniffer] playwright not installed")
        return {"type": "html", "html": ""}

    logger.info("[network-sniffer] start url=%s", url)

    input_domain = ".".join(urlparse(url).netloc.lower().split(".")[-2:])
    captured_apis: list[dict] = []

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

            async def _on_response(response):
                try:
                    if response.status >= 400:
                        return
                    ct = (response.headers.get("content-type") or "").lower()
                    if "json" not in ct and "javascript" not in ct:
                        return
                    resp_url = response.url
                    if _NOISE_EXTENSIONS.search(resp_url.split("?")[0]):
                        return
                    resp_host = urlparse(resp_url).netloc.lower()
                    if not resp_host.endswith(input_domain):
                        return
                    body = await response.text()
                    try:
                        data = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        return
                    if not _is_job_api_response(data):
                        return
                    request = response.request
                    captured_apis.append({
                        "api_url": resp_url,
                        "method": request.method,
                        "headers": dict(request.headers),
                        "post_data": request.post_data,
                        "sample": body[:10_000],
                    })
                    logger.info(
                        "[network-sniffer] captured api_url=%s items_count=%d",
                        resp_url,
                        len(body),
                    )
                except Exception as exc:
                    logger.debug("[network-sniffer] response handler error: %s", exc)

            page.on("response", _on_response)

            try:
                await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=_IDLE_WAIT_MS)
                except PWTimeout:
                    pass
            except PWTimeout:
                logger.warning("[network-sniffer] page load timed out url=%s", url)

            # Also scroll the page to trigger lazy-loaded API calls
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2_000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=3_000)
                except PWTimeout:
                    pass
            except Exception:
                pass

            if captured_apis:
                best = captured_apis[0]
                best["type"] = "api"
                logger.info(
                    "[network-sniffer] found api api_url=%s method=%s",
                    best["api_url"], best["method"],
                )
                return best

            html = await page.content()
            stripped = _strip_html(html)
            logger.info("[network-sniffer] no API found, returning html (%d chars)", len(stripped))
            return {"type": "html", "html": stripped}

        finally:
            await browser.close()
