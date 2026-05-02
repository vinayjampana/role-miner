"""4-step company career URL discovery: cache → heuristics → search → LLM."""
import json
import logging
import re
import sqlite3

import httpx
from openai import OpenAI

import config
from roleminer.registry.ats_detect import detect_ats_from_url, find_embedded_ats_url, workday_human_to_cxs
from roleminer.registry.db import get_all_companies, insert_company

logger = logging.getLogger(__name__)


def _name_to_domain_candidates(name: str) -> list[str]:
    clean = name.lower().strip()
    no_space = re.sub(r"[^a-z0-9]", "", clean)
    hyphen = re.sub(r"[^a-z0-9]+", "-", clean).strip("-")
    candidates = []
    for slug in dict.fromkeys([no_space, hyphen]):  # dedup, preserve order
        if slug:
            candidates.append(f"{slug}.com")
            candidates.append(f"{slug}.in")
    return candidates


def _careers_url_candidates(domain: str) -> list[str]:
    return [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://careers.{domain}",
        f"https://jobs.{domain}",
    ]


async def _expand_careers_url(url: str, client: httpx.AsyncClient) -> str:
    """
    Resolve a careers page URL to the scrappable ATS URL.

    Pass 1: static HTTP fetch → check final URL + scan HTML for ATS embed.
    Pass 2: headless browser render (JS-rendered pages, Workday hrefs, etc.).

    Returns the best URL found (CXS API URL for Workday, board URL for others).
    """
    if not url or not url.strip():
        logger.info("[discover-expand] empty input — skip")
        return url
    u0 = url.strip()
    logger.info("[discover-expand] step=fetch url=%s", u0)
    try:
        r = await client.get(u0, timeout=12.0, follow_redirects=True)
        final = str(r.url)
        det_f = detect_ats_from_url(final)
        logger.info(
            "[discover-expand] step=http status=%s final_url=%s detect(final)=%s",
            r.status_code,
            final,
            det_f,
        )
        if r.status_code >= 400:
            return u0
        if det_f:
            return workday_human_to_cxs(final) or final if det_f[0] == "workday" else final
        embedded = find_embedded_ats_url(r.text)
        if embedded:
            det_e = detect_ats_from_url(embedded)
            canonical = workday_human_to_cxs(embedded) or embedded if det_e and det_e[0] == "workday" else embedded
            logger.info("[discover-expand] step=html_scan bytes=%s embedded=%s", len(r.text or ""), canonical)
            return canonical
        logger.info("[discover-expand] step=html_scan bytes=%s no ATS found — trying browser", len(r.text or ""))
    except Exception as exc:
        logger.warning("[discover-expand] step=error %s — trying browser", exc)

    # Pass 2: headless browser for JS-rendered pages
    try:
        from roleminer.registry.browser_detect import detect_ats_with_browser
        browser_url, browser_det = await detect_ats_with_browser(u0)
        logger.info("[discover-expand] step=browser detect=%s url=%s", browser_det, browser_url)
        return browser_url
    except Exception as exc:
        logger.warning("[discover-expand] step=browser error: %s", exc)
    return u0


async def _probe(url: str, client: httpx.AsyncClient) -> str | None:
    """If URL responds, return ATS or final careers URL (HTML scan when no redirect to ATS)."""
    try:
        r = await client.get(url, timeout=12.0, follow_redirects=True)
        if r.status_code >= 400:
            logger.info("[discover-probe] seed=%s → no_hit status=%s", url, r.status_code)
            return None
        final = str(r.url)
        det = detect_ats_from_url(final)
        if det:
            canonical = workday_human_to_cxs(final) or final if det[0] == "workday" else final
            logger.info("[discover-probe] seed=%s → final=%s canonical=%s detect=%s", url, final, canonical, det)
            return canonical
        embedded = find_embedded_ats_url(r.text)
        if embedded:
            det_e = detect_ats_from_url(embedded)
            embedded = workday_human_to_cxs(embedded) or embedded if det_e and det_e[0] == "workday" else embedded
        out = embedded or final
        logger.info(
            "[discover-probe] seed=%s → final=%s embedded=%s out=%s",
            url,
            final,
            embedded,
            out,
        )
        return out
    except Exception as exc:
        logger.info("[discover-probe] seed=%s → error %s", url, exc)
        return None


async def _heuristic_search(name: str, client: httpx.AsyncClient) -> str | None:
    domains = _name_to_domain_candidates(name)
    logger.info("[discover] %r step=heuristic domain_candidates=%s", name, domains)
    for domain in domains:
        for url in _careers_url_candidates(domain):
            final = await _probe(url, client)
            if final:
                ats = detect_ats_from_url(final)
                logger.info(
                    "[discover] %r step=heuristic hit seed=%s resolved=%s ats=%s",
                    name,
                    url,
                    final,
                    ats,
                )
                return final
    logger.info("[discover] %r step=heuristic miss (tried all seeds)", name)
    return None


async def _brave_search(name: str, client: httpx.AsyncClient) -> str | None:
    if not config.BRAVE_SEARCH_API_KEY:
        if not getattr(_brave_search, "_no_key_logged", False):
            logger.info("[discover] Brave web search disabled — set BRAVE_SEARCH_API_KEY to enable")
            _brave_search._no_key_logged = True  # type: ignore[attr-defined]
        return None
    try:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": f'"{name}" careers jobs site', "count": 3},
            headers={"X-Subscription-Token": config.BRAVE_SEARCH_API_KEY, "Accept": "application/json"},
            timeout=8.0,
        )
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        for r in results:
            url = r.get("url", "")
            if any(kw in url.lower() for kw in ["careers", "jobs", "greenhouse", "lever", "ashby", "workday", "smartrecruiters"]):
                logger.info("[discover] %r step=search brave picked (keyword) url=%s", name, url)
                return url
        if results:
            u0 = results[0].get("url")
            logger.info("[discover] %r step=search brave picked (first) url=%s", name, u0)
            return u0
    except Exception as exc:
        logger.warning("Brave search failed for %s: %s", name, exc)
    return None


def _llm_batch(names: list[str]) -> list[dict]:
    if not names:
        return []
    if not config.LLM_API_KEY:
        logger.info("[discover] step=llm skipped — no LLM_API_KEY (%d names need URLs)", len(names))
        return []
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=config.LLM_API_KEY)
    names_str = "\n".join(f"- {n}" for n in names)
    prompt = (
        "For each company below, return their official careers/jobs page URL.\n"
        "Return ONLY a JSON array. Each object: "
        '{"name": "...", "domain": "...", "careers_url": "...", '
            '"ats_type": "greenhouse|lever|ashby|workday|smartrecruiters|custom|unknown", "ats_slug": "..."}\n'
        "ats_slug: slug from the ATS URL (e.g. boards.greenhouse.io/SLUG). Empty string if not applicable.\n"
        "If unknown, set careers_url to null.\n\n"
        f"Companies:\n{names_str}"
    )
    try:
        logger.info("[discover] step=llm request model=%s companies=%d", config.DISCOVER_MODEL, len(names))
        resp = client.chat.completions.create(
            model=config.DISCOVER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        logger.info("[discover] step=llm response rows=%d", len(parsed) if isinstance(parsed, list) else 0)
        return parsed
    except Exception as exc:
        logger.error("LLM batch discovery failed: %s", exc)
        return []


async def discover_companies(
    names: list[str],
    conn: sqlite3.Connection,
) -> list[dict]:
    """
    Run 4-step discovery for each name. Returns list of result dicts.

    Step 1 — cache: DB hit with known ATS → done.
    Step 2 — heuristic: probe common URL patterns, expand with browser.
    Step 3 — search: Brave web search + browser expand.
    Step 4 — LLM: batch prompt for any still missing OR resolved as "custom"
              (heuristic/search found a URL but couldn't identify the ATS).

    Saves discovered companies to DB automatically.
    """
    clean_names = [n.strip() for n in names if n.strip()]
    logger.info("[discover] start count=%d names=%s", len(clean_names), clean_names)
    existing = {c["name"].lower(): c for c in get_all_companies(conn)}

    # best_result tracks the per-name best result so far (keyed by name.lower()).
    # LLM phase may upgrade a "custom" entry to a known ATS.
    best_result: dict[str, dict] = {}
    needs_search: list[str] = []   # heuristic found nothing
    needs_llm: list[str] = []      # heuristic/search found URL but ats_type=custom

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
    ) as http:
        for name in names:
            name = name.strip()
            if not name:
                continue
            key = name.lower()

            # Step 1: cache / DB — skip if already has a non-custom ATS
            cached = existing.get(key)
            if cached and cached.get("ats_slug"):
                logger.info(
                    "[discover] %r step=cache hit ats=%s/%s",
                    name, cached.get("ats_type"), cached.get("ats_slug"),
                )
                best_result[key] = {
                    "name": name,
                    "found": True,
                    "careers_url": cached.get("careers_url"),
                    "ats_type": cached.get("ats_type"),
                    "ats_slug": cached.get("ats_slug"),
                    "domain": cached.get("domain"),
                    "method": "cache",
                    "already_in_db": True,
                    "company_id": cached.get("id"),
                }
                continue
            if cached and cached.get("careers_url") and cached.get("ats_type") not in (None, "", "custom"):
                logger.info(
                    "[discover] %r step=cache hit (workday) careers_url=%s",
                    name, cached.get("careers_url"),
                )
                best_result[key] = {
                    "name": name,
                    "found": True,
                    "careers_url": cached.get("careers_url"),
                    "ats_type": cached.get("ats_type"),
                    "ats_slug": cached.get("ats_slug"),
                    "domain": cached.get("domain"),
                    "method": "cache",
                    "already_in_db": True,
                    "company_id": cached.get("id"),
                }
                continue

            # Step 2: heuristics (static probe + browser expand built into _heuristic_search)
            logger.info("[discover] %r step=heuristic begin", name)
            url = await _heuristic_search(name, http)
            if url:
                ats = detect_ats_from_url(url)
                r: dict = {
                    "name": name,
                    "found": True,
                    "careers_url": url,
                    "ats_type": ats[0] if ats else "custom",
                    "ats_slug": ats[1] if ats else "",
                    "domain": None,
                    "method": "heuristic",
                    "already_in_db": bool(cached),
                    "company_id": None,
                }
                best_result[key] = r
                _save_result(r, conn, cached)
                logger.info("[discover] %r step=heuristic ats=%s/%s url=%s", name, r["ats_type"], r["ats_slug"], url)
                if r["ats_type"] == "custom":
                    needs_llm.append(name)  # found URL but no ATS — try LLM refinement
                continue

            needs_search.append(name)

        # Step 3: web search for heuristic misses
        logger.info("[discover] step=search phase count=%d", len(needs_search))
        for name in needs_search:
            key = name.lower()
            cached = existing.get(key)
            logger.info("[discover] %r step=search begin", name)
            url = await _brave_search(name, http)
            if url:
                url = await _expand_careers_url(url, http)
                ats = detect_ats_from_url(url)
                r = {
                    "name": name,
                    "found": True,
                    "careers_url": url,
                    "ats_type": ats[0] if ats else "custom",
                    "ats_slug": ats[1] if ats else "",
                    "domain": None,
                    "method": "search",
                    "already_in_db": bool(cached),
                    "company_id": None,
                }
                best_result[key] = r
                _save_result(r, conn, cached)
                logger.info("[discover] %r step=search ats=%s/%s url=%s", name, r["ats_type"], r["ats_slug"], url)
                if r["ats_type"] == "custom":
                    needs_llm.append(name)
            else:
                logger.info("[discover] %r step=search miss → LLM", name)
                needs_llm.append(name)

        # Step 4: LLM — for misses AND custom-only results (Option B)
        if needs_llm:
            logger.info("[discover] step=llm phase count=%d names=%s", len(needs_llm), needs_llm)
            llm_results = _llm_batch(needs_llm)
            llm_map = {r.get("name", "").lower(): r for r in llm_results}
            for name in needs_llm:
                key = name.lower()
                lr = llm_map.get(key)
                cached = existing.get(key)
                prior = best_result.get(key)  # may have a careers_url from heuristic/search

                if lr and lr.get("careers_url"):
                    raw_llm = lr["careers_url"]
                    logger.info("[discover] %r step=llm raw=%s llm_ats=%s/%s", name, raw_llm, lr.get("ats_type"), lr.get("ats_slug"))
                    url = await _expand_careers_url(raw_llm, http)
                    ats_from_url = detect_ats_from_url(url)
                    ats_type = ats_from_url[0] if ats_from_url else lr.get("ats_type")
                    ats_slug = ats_from_url[1] if ats_from_url else lr.get("ats_slug", "")

                    # Only upgrade if LLM gave a better (non-custom) result
                    if ats_type in (None, "custom", "unknown") and prior:
                        logger.info("[discover] %r step=llm kept prior (LLM also custom)", name)
                        continue

                    r = {
                        "name": name,
                        "found": True,
                        "careers_url": url,
                        "ats_type": ats_type,
                        "ats_slug": ats_slug,
                        "domain": lr.get("domain"),
                        "method": "llm",
                        "already_in_db": bool(cached),
                        "company_id": None,
                    }
                    best_result[key] = r
                    _save_result(r, conn, cached)
                    logger.info("[discover] %r step=llm saved ats=%s/%s url=%s", name, ats_type, ats_slug, url)
                else:
                    logger.info("[discover] %r step=llm no careers_url — row=%s", name, lr)
                    if not prior:
                        best_result[key] = {
                            "name": name,
                            "found": False,
                            "careers_url": None,
                            "ats_type": None,
                            "ats_slug": None,
                            "domain": None,
                            "method": "failed",
                            "already_in_db": bool(cached),
                            "company_id": None,
                        }

    results = list(best_result.values())
    found_n = sum(1 for x in results if x.get("found"))
    logger.info("[discover] complete results=%d found=%d", len(results), found_n)
    return results


def _save_result(r: dict, conn: sqlite3.Connection, existing: dict | None) -> None:
    if existing:
        fields: dict = {}
        if r.get("careers_url") and not existing.get("careers_url"):
            fields["careers_url"] = r["careers_url"]
        if r.get("ats_type") and not existing.get("ats_type"):
            fields["ats_type"] = r["ats_type"]
        elif existing.get("ats_type") == "custom" and r.get("ats_type") not in (None, "", "custom"):
            fields["ats_type"] = r["ats_type"]
            if r.get("careers_url"):
                fields["careers_url"] = r["careers_url"]
            if r.get("ats_slug"):
                fields["ats_slug"] = r["ats_slug"]
        if r.get("ats_slug") and not existing.get("ats_slug"):
            fields["ats_slug"] = r["ats_slug"]
        if r.get("domain") and not existing.get("domain"):
            fields["domain"] = r["domain"]
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", [*fields.values(), existing["id"]])
            conn.commit()
            r["company_id"] = existing["id"]
            r["already_in_db"] = True
            logger.info("[discover] db update company_id=%s fields=%s", existing["id"], fields)
        else:
            logger.info("[discover] db update company_id=%s skipped (no empty fields to fill)", existing["id"])
    else:
        row_id = insert_company(conn, {
            "name": r["name"],
            "domain": r.get("domain"),
            "careers_url": r.get("careers_url"),
            "ats_type": r.get("ats_type"),
            "ats_slug": r.get("ats_slug") or "",
            "company_type": "product",
        })
        r["company_id"] = row_id
        r["already_in_db"] = False
        logger.info(
            "[discover] db insert company_id=%s name=%r ats=%s/%s url=%s",
            row_id,
            r["name"],
            r.get("ats_type"),
            r.get("ats_slug"),
            r.get("careers_url"),
        )
