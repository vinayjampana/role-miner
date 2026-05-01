"""Tests for dedup_by_url."""
import pytest
from roleminer.scrapers.base import Job, dedup_by_url


def _make_job(url: str, title: str = "Engineer") -> Job:
    return Job(
        title=title,
        company="Test Co",
        url=url,
        date_posted="2026-04-28T00:00:00Z",
        location="Bangalore",
        source="greenhouse",
    )


def test_dedup_removes_duplicates():
    """7 unique + 3 duplicate URLs → 7 unique jobs after dedup."""
    unique_urls = [f"https://example.com/job/{i}" for i in range(7)]
    duplicate_urls = [unique_urls[0], unique_urls[2], unique_urls[5]]  # 3 dupes

    jobs = [_make_job(url) for url in unique_urls + duplicate_urls]
    assert len(jobs) == 10

    result = dedup_by_url(jobs)
    assert len(result) == 7


def test_dedup_preserves_order():
    """First occurrence of each URL is kept."""
    jobs = [
        _make_job("https://example.com/1", title="First"),
        _make_job("https://example.com/2", title="Second"),
        _make_job("https://example.com/1", title="Duplicate of First"),
    ]
    result = dedup_by_url(jobs)
    assert len(result) == 2
    assert result[0].title == "First"
    assert result[1].title == "Second"


def test_dedup_empty_list():
    """Dedup of empty list returns empty list."""
    assert dedup_by_url([]) == []


def test_dedup_all_unique():
    """All unique URLs → no items removed."""
    jobs = [_make_job(f"https://example.com/job/{i}") for i in range(5)]
    result = dedup_by_url(jobs)
    assert len(result) == 5


def test_dedup_all_same_url():
    """All same URL → only 1 job returned."""
    jobs = [_make_job("https://example.com/job/1") for _ in range(5)]
    result = dedup_by_url(jobs)
    assert len(result) == 1
