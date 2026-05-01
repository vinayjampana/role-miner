"""Tests for filter_jobs — freshness, location, salary, company type, blocklist."""
import pytest
from datetime import datetime, timezone, timedelta
from roleminer.scrapers.base import Job
from roleminer.pipeline.filter import filter_jobs


def _make_job(**kwargs) -> Job:
    defaults = dict(
        title="Senior Engineer",
        company="TestCo",
        url="https://example.com/job/1",
        date_posted=(datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat(),
        location="Bangalore",
        source="greenhouse",
        work_mode="onsite",
        company_type="product",
    )
    defaults.update(kwargs)
    return Job(**defaults)


_BASE_PROFILE = {
    "skills": ["React", "TypeScript"],
    "locations": ["Bangalore", "Remote"],
    "salary_min_lpa": 30,
    "work_mode": ["remote", "hybrid", "onsite"],
    "company_type": ["product"],
    "exclude_companies": [],
    "notice_days": 60,
}


def test_stale_job_filtered_out():
    """Job posted more than 7 days ago is filtered out."""
    old_date = (datetime.now(tz=timezone.utc) - timedelta(days=10)).isoformat()
    job = _make_job(date_posted=old_date)
    result = filter_jobs([job], _BASE_PROFILE)
    assert result == []


def test_fresh_job_passes():
    """Job posted 1 day ago passes the freshness filter."""
    job = _make_job()
    result = filter_jobs([job], _BASE_PROFILE)
    assert len(result) == 1


def test_wrong_location_filtered():
    """Job in USA (not in profile locations) is filtered out."""
    job = _make_job(location="San Francisco, USA", work_mode="onsite")
    result = filter_jobs([job], _BASE_PROFILE)
    assert result == []


def test_remote_job_passes_even_without_india_location():
    """Remote job passes when 'remote' is in profile.work_mode."""
    job = _make_job(location="USA", work_mode="remote")
    result = filter_jobs([job], _BASE_PROFILE)
    assert len(result) == 1


def test_salary_below_minimum_filtered():
    """Job with max salary 20 LPA when profile wants 30 LPA → filtered."""
    job = _make_job(salary_lpa={"min": 10, "max": 20})
    result = filter_jobs([job], _BASE_PROFILE)
    assert result == []


def test_salary_above_minimum_passes():
    """Job with max salary 50 LPA when profile wants 30 LPA → passes."""
    job = _make_job(salary_lpa={"min": 30, "max": 50})
    result = filter_jobs([job], _BASE_PROFILE)
    assert len(result) == 1


def test_no_salary_passes():
    """Job with no salary info is NOT filtered out (no salary → assume OK)."""
    job = _make_job(salary_lpa=None)
    result = filter_jobs([job], _BASE_PROFILE)
    assert len(result) == 1


def test_service_company_filtered_when_profile_is_product_only():
    """Service company filtered when profile.company_type = ['product']."""
    job = _make_job(company_type="service")
    result = filter_jobs([job], _BASE_PROFILE)
    assert result == []


def test_blocklisted_company_filtered():
    """Company in exclude_companies is filtered out (case-insensitive)."""
    profile = {**_BASE_PROFILE, "exclude_companies": ["TestCo"]}
    job = _make_job(company="testco")
    result = filter_jobs([job], profile)
    assert result == []


def test_multiple_jobs_mixed():
    """Mix of good and bad jobs — only passing ones returned."""
    good = _make_job(url="https://example.com/good")
    stale = _make_job(
        url="https://example.com/stale",
        date_posted=(datetime.now(tz=timezone.utc) - timedelta(days=10)).isoformat(),
    )
    wrong_loc = _make_job(url="https://example.com/wrong_loc", location="New York, USA", work_mode="onsite")

    result = filter_jobs([good, stale, wrong_loc], _BASE_PROFILE)
    assert len(result) == 1
    assert result[0].url == "https://example.com/good"
