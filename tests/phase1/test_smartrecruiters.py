"""Live HTTP tests for SmartRecruiters public API scraper."""

import pytest

from roleminer.scrapers.base import make_session
from roleminer.scrapers import smartrecruiters


@pytest.mark.asyncio
async def test_smartrecruiters_freshworks_live():
    async with make_session() as session:
        jobs = await smartrecruiters.scrape("Freshworks", session, company_name="Freshworks")

    assert isinstance(jobs, list)
    assert len(jobs) > 0
    for job in jobs:
        assert job.title
        assert job.url.startswith("https://jobs.smartrecruiters.com/Freshworks/")
        assert job.source == "smartrecruiters"
        assert job.company == "Freshworks"
        assert job.work_mode in ("remote", "hybrid", "onsite")


@pytest.mark.asyncio
async def test_smartrecruiters_invalid_identifier():
    async with make_session() as session:
        jobs = await smartrecruiters.scrape("this-company-does-not-exist-xyz999", session)
    assert jobs == []
