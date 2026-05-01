"""Tests for Job and ScoredJob dataclasses."""
import pytest
from roleminer.scrapers.base import Job, ScoredJob


def test_job_defaults():
    """Job has correct default values for optional fields."""
    job = Job(
        title="Senior Engineer",
        company="Acme",
        url="https://example.com/job/1",
        date_posted="2026-04-28T10:00:00Z",
        location="Bangalore",
        source="greenhouse",
    )
    assert job.work_mode == "onsite"
    assert job.salary_lpa is None
    assert job.jd_text == ""
    assert job.funding_stage == ""
    assert job.has_esop is False
    assert job.company_type == ""
    assert job.notice_compatible is True


def test_job_required_fields():
    """Job stores all required fields correctly."""
    job = Job(
        title="Staff Engineer",
        company="Razorpay",
        url="https://boards.greenhouse.io/razorpay/jobs/42",
        date_posted="2026-04-30T00:00:00Z",
        location="Bangalore, India",
        source="greenhouse",
    )
    assert job.title == "Staff Engineer"
    assert job.company == "Razorpay"
    assert job.source == "greenhouse"


def test_job_custom_fields():
    """Job accepts all optional fields."""
    job = Job(
        title="Remote SWE",
        company="TestCo",
        url="https://example.com/job/2",
        date_posted="2026-04-29T00:00:00Z",
        location="Remote",
        source="lever",
        work_mode="remote",
        salary_lpa={"min": 30, "max": 50},
        jd_text="We offer ESOP and hybrid work.",
        funding_stage="Series B",
        has_esop=True,
        company_type="product",
        notice_compatible=False,
    )
    assert job.work_mode == "remote"
    assert job.salary_lpa == {"min": 30, "max": 50}
    assert job.has_esop is True
    assert job.company_type == "product"
    assert job.notice_compatible is False


def test_scored_job_from_job_copies_all_fields():
    """ScoredJob.from_job() preserves every field from the source Job."""
    job = Job(
        title="Senior Engineer",
        company="Sarvam AI",
        url="https://example.com/job/3",
        date_posted="2026-04-28T00:00:00Z",
        location="Bangalore",
        source="ashby",
        work_mode="hybrid",
        salary_lpa={"min": 40, "max": 70},
        jd_text="ESOP available for all.",
        funding_stage="Series A",
        has_esop=True,
        company_type="product",
        notice_compatible=True,
    )

    scored = ScoredJob.from_job(job, score=8, reason="strong fit", skill_gap={"have": ["React"], "need": ["Rust"], "gap": ["Rust"]})

    assert scored.title == job.title
    assert scored.company == job.company
    assert scored.url == job.url
    assert scored.date_posted == job.date_posted
    assert scored.location == job.location
    assert scored.source == job.source
    assert scored.work_mode == job.work_mode
    assert scored.salary_lpa == job.salary_lpa
    assert scored.jd_text == job.jd_text
    assert scored.funding_stage == job.funding_stage
    assert scored.has_esop == job.has_esop
    assert scored.company_type == job.company_type
    assert scored.notice_compatible == job.notice_compatible
    assert scored.score == 8
    assert scored.reason == "strong fit"
    assert scored.skill_gap == {"have": ["React"], "need": ["Rust"], "gap": ["Rust"]}


def test_scored_job_from_job_default_skill_gap():
    """ScoredJob.from_job() with no skill_gap uses empty default."""
    job = Job(
        title="Engineer",
        company="Co",
        url="https://example.com",
        date_posted="2026-04-28T00:00:00Z",
        location="Mumbai",
        source="lever",
    )
    scored = ScoredJob.from_job(job)
    assert scored.score == 0
    assert scored.reason == ""
    assert scored.skill_gap == {"have": [], "need": [], "gap": []}


def test_scored_job_independent_skill_gap_instances():
    """Each ScoredJob gets its own default skill_gap dict (no shared mutable default)."""
    job = Job(
        title="Eng",
        company="Co",
        url="https://example.com/a",
        date_posted="2026-04-28T00:00:00Z",
        location="Hyderabad",
        source="greenhouse",
    )
    s1 = ScoredJob.from_job(job)
    s2 = ScoredJob.from_job(job)
    s1.skill_gap["have"].append("React")
    assert s2.skill_gap["have"] == []
