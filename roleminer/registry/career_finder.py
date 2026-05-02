"""4-step company career URL discovery: cache → heuristics → search → LLM."""
import json
import logging
import re
import sqlite3

import httpx
from openai import OpenAI

import config
from roleminer.registry.db import get_all_companies, insert_company

logger = logging.getLogger(__name__)

_ATS_URL_PATTERNS = [
    (re.compile(r"boards\.greenhouse\.io/([^/?#]+)"), "greenhouse"),
    (re.compile(r"jobs\.lever\.co/([^/?#]+)"), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"), "ashby"),
    (re.compile(r"([^.]+)\.wd\d+\.myworkdayjobs\.com"), "workday"),
]


def _detect_ats(url: str) -> tuple[str, str] | None:
    for pattern, ats_type in _ATS_URL_PATTERNS:
        m = pattern.search(url or "")
        if m:
            return ats_type, m.group(1)
    return None


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


async def _probe(url: str, client: httpx.AsyncClient) -> bool:
    try:
        r = await client.head(url, timeout=5.0, follow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


async def _heuristic_search(name: str, client: httpx.AsyncClient) -> str | None:
    for domain in _name_to_domain_candidates(name):
        for url in _careers_url_candidates(domain):
            if await _probe(url, client):
                logger.debug("heuristic hit: %s → %s", name, url)
                return url
    return None


async def _brave_search(name: str, client: httpx.AsyncClient) -> str | None:
    if not config.BRAVE_SEARCH_API_KEY:
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
                return url
        if results:
            return results[0].get("url")
    except Exception as exc:
        logger.warning("Brave search failed for %s: %s", name, exc)
    return None


def _llm_batch(names: list[str]) -> list[dict]:
    if not names or not config.LLM_API_KEY:
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
        resp = client.chat.completions.create(
            model=config.DISCOVER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
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
    existing = {c["name"].lower(): c for c in get_all_companies(conn)}
    results: list[dict] = []
    needs_search: list[str] = []  # heuristic failed, needs search/LLM
    needs_llm: list[str] = []

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
            url = await _heuristic_search(name, http)
            if url:
                ats = _detect_ats(url)
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
                _save_result(r, conn, cached)
                continue

            needs_search.append(name)

        # Step 3: web search for misses
        still_missing: list[str] = []
        for name in needs_search:
            # check if already resolved by heuristic above
            if any(r["name"] == name and r["method"] == "heuristic" for r in results):
                continue
            url = await _brave_search(name, http)
            if url:
                ats = _detect_ats(url)
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
                _save_result(r, conn, cached)
            else:
                still_missing.append(name)

    # Step 4: LLM batch for all remaining
    if still_missing:
        llm_results = _llm_batch(still_missing)
        llm_map = {r.get("name", "").lower(): r for r in llm_results}
        for name in still_missing:
            lr = llm_map.get(name.lower())
            cached = existing.get(name.lower())
            if lr and lr.get("careers_url"):
                url = lr["careers_url"]
                ats_from_url = _detect_ats(url)
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
                _save_result(r, conn, cached)
            else:
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

    return results


def _save_result(r: dict, conn: sqlite3.Connection, existing: dict | None) -> None:
    if existing:
        # update careers_url / ats info if missing
        from roleminer.registry.db import update_run  # avoid circular; use raw SQL
        fields: dict = {}
        if r.get("careers_url") and not existing.get("careers_url"):
            fields["careers_url"] = r["careers_url"]
        if r.get("ats_type") and not existing.get("ats_type"):
            fields["ats_type"] = r["ats_type"]
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
