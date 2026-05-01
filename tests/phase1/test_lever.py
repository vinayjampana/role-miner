"""Live HTTP test for Lever scraper using the 'plaid' board."""
import pytest
import httpx
from roleminer.scrapers.base import make_session
from roleminer.scrapers import lever


async def test_lever_plaid_live():
    """Plaid has a public Lever board — should return jobs with expected fields."""
    async with make_session() as session:
        jobs = await lever.scrape("plaid", session, company_name="Plaid")

    assert isinstance(jobs, list), "Should return a list"
    assert len(jobs) > 0, "Plaid Lever board should have at least 1 job"

    for job in jobs:
        assert job.title, f"Job missing title: {job}"
        assert job.url, f"Job missing url: {job}"
        assert job.date_posted, f"Job missing date_posted: {job}"
        assert job.source == "lever"
        assert job.company == "Plaid"
        assert job.work_mode in ("remote", "hybrid", "onsite")


async def test_lever_invalid_slug_returns_empty():
    """An invalid/not-found slug should return an empty list without raising."""
    async with make_session() as session:
        jobs = await lever.scrape("this-slug-does-not-exist-xyz9999", session)

    # Lever returns {"ok": false, "error": "..."} for invalid slugs — we return []
    assert isinstance(jobs, list)
    assert jobs == []
