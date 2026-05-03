"""Discovery Agent — orchestrates strategy discovery for custom career sites.

Pipeline:
1. Load companies with ats_type='custom' (or any company needing a strategy)
2. Run network sniffer on their careers_url
3. Pass sniffer output to the LLM strategy builder
4. Persist the resulting ScrapeStrategy to the database
"""
from __future__ import annotations

import logging
import sqlite3

from roleminer.registry.db import get_company, upsert_company
from roleminer.registry.network_sniffer import sniff_career_page
from roleminer.registry.strategy_builder import generate_scrape_strategy

logger = logging.getLogger(__name__)


async def discover_strategy_for_company(
    conn: sqlite3.Connection,
    company_id: int,
) -> dict | None:
    """Run the full discovery pipeline for a single company.

    Steps:
        1. Load company from DB, check it has a careers_url
        2. Sniff the career page for APIs or capture HTML
        3. Generate a scrape strategy via LLM
        4. Persist the strategy to the DB

    Args:
        conn: SQLite connection
        company_id: Company row id

    Returns:
        The validated strategy dict, or None on failure.
    """
    company = get_company(conn, company_id)
    if not company:
        logger.warning("[discovery-agent] company id=%d not found", company_id)
        return None

    name = company.get("name", "")
    careers_url = (company.get("careers_url") or "").strip()
    existing = company.get("scrape_strategy")

    if existing and company.get("strategy_status") == "active":
        logger.info(
            "[discovery-agent] company=%r already has active strategy — skipping",
            name,
        )
        return existing

    if not careers_url:
        logger.warning("[discovery-agent] company=%r has no careers_url — skipping", name)
        return None

    logger.info("[discovery-agent] start company=%r url=%s", name, careers_url)

    sniffer_data = await sniff_career_page(careers_url)
    data_type = sniffer_data.get("type", "unknown")
    logger.info("[discovery-agent] sniffer result type=%s for company=%r", data_type, name)

    if data_type == "html" and not sniffer_data.get("html", "").strip():
        logger.warning("[discovery-agent] sniffer returned empty data for company=%r", name)
        _mark_failed(conn, company_id)
        return None

    strategy = await generate_scrape_strategy(name, sniffer_data)
    if not strategy:
        logger.warning("[discovery-agent] strategy generation failed for company=%r", name)
        _mark_failed(conn, company_id)
        return None

    upsert_company(conn, {
        "name": name,
        "scrape_strategy": strategy,
        "strategy_status": "active",
    })
    logger.info(
        "[discovery-agent] saved strategy for company=%r type=%s",
        name, strategy.get("strategy_type"),
    )
    return strategy


async def discover_strategies_batch(
    conn: sqlite3.Connection,
    company_ids: list[int],
) -> dict[int, dict | None]:
    """Run discovery for multiple companies.

    Returns:
        dict mapping company_id → strategy (or None if failed/skipped).
    """
    results: dict[int, dict | None] = {}
    for cid in company_ids:
        try:
            strategy = await discover_strategy_for_company(conn, cid)
            results[cid] = strategy
        except Exception as exc:
            logger.error("[discovery-agent] failed for company_id=%d: %s", cid, exc)
            _mark_failed(conn, cid)
            results[cid] = None
    return results


def _mark_failed(conn: sqlite3.Connection, company_id: int) -> None:
    from roleminer.registry.db import update_company_fields
    update_company_fields(conn, company_id, {"strategy_status": "failed"})
