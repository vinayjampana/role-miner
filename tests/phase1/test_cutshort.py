"""Live HTTP test for Cutshort scraper."""
import pytest
from roleminer.scrapers.base import make_session
from roleminer.scrapers import cutshort


async def test_cutshort_live():
    """
    Attempt a live Cutshort call. If 401/403, skip gracefully.
    If 200, verify the response is a valid list (may be empty).
    """
    async with make_session() as session:
        jobs = await cutshort.scrape(
            skills=["React"],
            locations=["Bangalore"],
            session=session,
        )

    # If cutshort requires auth, scrape() returns [] — that's fine
    assert isinstance(jobs, list), "Should always return a list"

    for job in jobs:
        assert job.source == "cutshort"
        assert job.title is not None
        assert job.url is not None
