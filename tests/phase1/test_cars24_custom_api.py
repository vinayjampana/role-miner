"""Live integration: Cars24 careers → JS API discovery → JSON scrape (no LLM)."""

from __future__ import annotations

import pytest

from roleminer.registry.job_api_discover import discover_job_api_with_alternate_host
from roleminer.scrapers.base import make_session
from roleminer.scrapers import custom as custom_scraper


@pytest.mark.asyncio
async def test_cars24_discover_and_scrape_json_api():
    careers = "https://www.cars24.com/careers/"
    async with make_session() as session:
        r = await session.get(careers, follow_redirects=True, timeout=25.0)
        assert r.status_code < 400
        api_url = await discover_job_api_with_alternate_host(session, r.text, str(r.url))
        assert api_url, "expected API URL from www careers + careers.* fallback"
        assert "joblist" in api_url.lower() or "job-filter" in api_url.lower()

        jobs = await custom_scraper.scrape_json_api(api_url, session, company_name="Cars24")
        assert len(jobs) >= 200, f"expected full listing (~223), got {len(jobs)}"
        assert all(j.url.startswith("http") for j in jobs)
        assert all("careers.cars24.com" in j.url for j in jobs[:20])
        titles = {j.title.lower() for j in jobs}
        assert any("engineer" in t or "manager" in t for t in titles)
