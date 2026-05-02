"""4-step company career URL discovery: cache → heuristics → search → LLM."""
import json
import logging
import re
import sqlite3

import httpx
from openai import OpenAI

import config
from roleminer.registry.ats_detect import detect_ats_from_url, find_embedded_ats_url
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
    Final URL after redirects; if the page stays on the corporate domain, scan HTML
    for embedded Greenhouse / Lever / Ashby / Workday board URLs.
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
            return final
        embedded = find_embedded_ats_url(r.text)
        out = embedded or final
        logger.info(
            "[discover-expand] step=html_scan bytes=%s embedded=%s → out=%s",
            len(r.text or ""),
            embedded,
            out,
        )
        return out
    except Exception as exc:
        logger.warning("[discover-expand] step=error %s — return original url", exc)
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
            logger.info("[discover-probe] seed=%s → final=%s detect=%s", url, final, det)
            return final
        embedded = find_embedded_ats_url(r.text)
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
            if any(kw in url.lower() for kw in ["careers", "jobs", "greenhouse", "lever", "ashby", "workday"]):
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
        '"ats_type": "greenhouse|lever|ashby|workday|custom|unknown", "ats_slug": "..."}\n'
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
    Saves discovered companies to DB automatically.
    """
    clean_names = [n.strip() for n in names if n.strip()]
    logger.info("[discover] start count=%d names=%s", len(clean_names), clean_names)
    existing = {c["name"].lower(): c for c in get_all_companies(conn)}
    results: list[dict] = []
    needs_search: list[str] = []  # heuristic failed, needs search/LLM

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
    ) as http:
        for name in names:
            name = name.strip()
            if not name:
                continue

            # Step 1: cache / DB
            cached = existing.get(name.lower())
            if cached and (cached.get("careers_url") or cached.get("ats_slug")):
                logger.info(
                    "[discover] %r step=cache hit company_id=%s careers_url=%s ats=%s/%s",
                    name,
                    cached.get("id"),
                    cached.get("careers_url"),
                    cached.get("ats_type"),
                    cached.get("ats_slug"),
                )
                results.append({
                    "name": name,
                    "found": True,
                    "careers_url": cached.get("careers_url"),
                    "ats_type": cached.get("ats_type"),
                    "ats_slug": cached.get("ats_slug"),
                    "domain": cached.get("domain"),
                    "method": "cache",
                    "already_in_db": True,
                    "company_id": cached.get("id"),
                })
                continue

            # Step 2: heuristics
            logger.info("[discover] %r step=heuristic begin (not in cache with url/slug)", name)
            url = await _heuristic_search(name, http)
            if url:
                ats = detect_ats_from_url(url)
                r = {
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
                results.append(r)
                needs_search.append(name)  # still mark for save after this
                logger.info(
                    "[discover] %r step=heuristic save ats=%s/%s url=%s",
                    name,
                    r["ats_type"],
                    r["ats_slug"],
                    r["careers_url"],
                )
                _save_result(r, conn, cached)
                continue

            needs_search.append(name)

        # Step 3: web search for misses
        still_missing: list[str] = []
        logger.info("[discover] step=search phase needs_search=%d", len(needs_search))
        for name in needs_search:
            # check if already resolved by heuristic above
            if any(r["name"] == name and r["method"] == "heuristic" for r in results):
                continue
            logger.info("[discover] %r step=search brave_query begin", name)
            url = await _brave_search(name, http)
            if url:
                url = await _expand_careers_url(url, http)
                ats = detect_ats_from_url(url)
                cached = existing.get(name.lower())
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
                results.append(r)
                logger.info(
                    "[discover] %r step=search save ats=%s/%s url=%s",
                    name,
                    r["ats_type"],
                    r["ats_slug"],
                    r["careers_url"],
                )
                _save_result(r, conn, cached)
            else:
                logger.info("[discover] %r step=search miss → will try LLM", name)
                still_missing.append(name)

        # Step 4: LLM batch for all remaining (expand URLs inside same client scope)
        if still_missing:
            logger.info("[discover] step=llm phase still_missing=%d %s", len(still_missing), still_missing)
            llm_results = _llm_batch(still_missing)
            llm_map = {r.get("name", "").lower(): r for r in llm_results}
            for name in still_missing:
                lr = llm_map.get(name.lower())
                cached = existing.get(name.lower())
                if lr and lr.get("careers_url"):
                    raw_llm = lr["careers_url"]
                    logger.info("[discover] %r step=llm raw careers_url=%s llm_ats=%s/%s", name, raw_llm, lr.get("ats_type"), lr.get("ats_slug"))
                    url = await _expand_careers_url(raw_llm, http)
                    ats_from_url = detect_ats_from_url(url)
                    r = {
                        "name": name,
                        "found": True,
                        "careers_url": url,
                        "ats_type": ats_from_url[0] if ats_from_url else lr.get("ats_type"),
                        "ats_slug": ats_from_url[1] if ats_from_url else lr.get("ats_slug", ""),
                        "domain": lr.get("domain"),
                        "method": "llm",
                        "already_in_db": bool(cached),
                        "company_id": None,
                    }
                    results.append(r)
                    logger.info(
                        "[discover] %r step=llm save expanded_url=%s ats=%s/%s (from_url=%s)",
                        name,
                        url,
                        r["ats_type"],
                        r["ats_slug"],
                        ats_from_url,
                    )
                    _save_result(r, conn, cached)
                else:
                    logger.info("[discover] %r step=llm failed no careers_url in LLM row=%s", name, lr)
                    results.append({
                        "name": name,
                        "found": False,
                        "careers_url": None,
                        "ats_type": None,
                        "ats_slug": None,
                        "domain": None,
                        "method": "failed",
                        "already_in_db": bool(cached),
                        "company_id": None,
                    })

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
