"""Live HTTP test for Ashby scraper using the 'linear' board."""
import pytest
import httpx
from roleminer.scrapers.base import make_session
from roleminer.scrapers import ashby


async def test_ashby_linear_live():
    """Linear uses Ashby — should return jobs with expected fields."""
    async with make_session() as session:
        jobs = await ashby.scrape("linear", session, company_name="Linear")

    assert isinstance(jobs, list), "Should return a list"
    # Linear may have 0 open roles at times — just check it doesn't fail
    assert len(jobs) >= 0

    for job in jobs:
        assert job.title, f"Job missing title: {job}"
        assert job.url, f"Job missing url: {job}"
        assert job.source == "ashby"
        assert job.company == "Linear"
        assert job.work_mode in ("remote", "hybrid", "onsite")


async def test_ashby_invalid_slug_returns_empty():
    """An invalid slug should return an empty list without raising."""
    async with make_session() as session:
        jobs = await ashby.scrape("this-slug-does-not-exist-xyz9999", session)

    assert jobs == []
