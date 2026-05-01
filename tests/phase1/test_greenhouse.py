"""Live HTTP test for Greenhouse scraper using the 'postman' board."""
import pytest
import httpx
from roleminer.scrapers.base import make_session
from roleminer.scrapers import greenhouse


async def test_greenhouse_postman_live():
    """Postman has a public Greenhouse board — should return jobs with expected fields."""
    async with make_session() as session:
        jobs = await greenhouse.scrape("postman", session, company_name="Postman")

    assert isinstance(jobs, list), "Should return a list"
    assert len(jobs) > 0, "Postman Greenhouse board should have at least 1 job"

    for job in jobs:
        assert job.title, f"Job missing title: {job}"
        assert job.url, f"Job missing url: {job}"
        assert job.date_posted, f"Job missing date_posted: {job}"
        assert job.location is not None, f"Job missing location: {job}"
        assert job.source == "greenhouse"
        assert job.company == "Postman"
        assert job.work_mode in ("remote", "hybrid", "onsite")


async def test_greenhouse_invalid_slug_returns_empty():
    """An invalid slug should return an empty list without raising."""
    async with make_session() as session:
        jobs = await greenhouse.scrape("this-slug-does-not-exist-xyz9999", session)

    assert jobs == []
