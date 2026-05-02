"""Tests for ATS URL detection (registry/ats_detect.py)."""
import pytest

from roleminer.registry.ats_detect import detect_ats_from_url, find_embedded_ats_url


@pytest.mark.parametrize(
    "url,expected",
    [
        # Greenhouse — standard hosts
        ("https://boards.greenhouse.io/razorpay", ("greenhouse", "razorpay")),
        ("http://boards.greenhouse.io/acme-corp", ("greenhouse", "acme-corp")),
        ("https://job-boards.greenhouse.io/meesho", ("greenhouse", "meesho")),
        (
            "https://boards.greenhouse.io/embed/job_board?for=stripe&token=abc",
            ("greenhouse", "stripe"),
        ),
        # Slug with query fragment on board path still parses slug
        ("https://boards.greenhouse.io/groww?utm_source=linkedin", ("greenhouse", "groww")),
        # URL-encoded slug (Lever / Ashby)
        ("https://jobs.lever.co/hello%20world", ("lever", "hello world")),
        ("https://jobs.eu.lever.co/acme", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/foo%2Fbar", ("ashby", "foo/bar")),
        # Workday — JSON API path stored in registry
        (
            "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs",
            ("workday", ""),
        ),
        (
            "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs",
            ("workday", ""),
        ),
    ],
)
def test_detect_ats_positive(url, expected):
    assert detect_ats_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "https://example.com/careers",
        "https://careers.google.com/jobs",
        # Workday public job detail — not the cxs API URL we scrape
        "https://paypal.wd1.myworkdayjobs.com/en-US/job/Bangalore/Engineer_123",
        # Host looks like Greenhouse but is not boards / job-boards
        "https://greenhouse.io/blog/boards/foo",
    ],
)
def test_detect_ats_negative(url):
    assert detect_ats_from_url(url) is None


def test_detect_ats_lever_ashby_basic():
    assert detect_ats_from_url("https://jobs.lever.co/company-name") == ("lever", "company-name")
    assert detect_ats_from_url("https://jobs.ashbyhq.com/ashby-slug") == ("ashby", "ashby-slug")


@pytest.mark.parametrize(
    "html,expected_substr",
    [
        (
            '<iframe src="https://boards.greenhouse.io/acmecorp"></iframe>',
            "https://boards.greenhouse.io/acmecorp",
        ),
        (
            "<p>Apply at //job-boards.greenhouse.io/foo-careers</p>",
            "https://job-boards.greenhouse.io/foo-careers",
        ),
        (
            'href="https://jobs.lever.co/team-x" class="btn"',
            "https://jobs.lever.co/team-x",
        ),
        (
            "window.location = 'https://jobs.ashbyhq.com/uuid-slug';",
            "https://jobs.ashbyhq.com/uuid-slug",
        ),
    ],
)
def test_find_embedded_ats_url(html, expected_substr):
    found = find_embedded_ats_url(html)
    assert found is not None
    assert found == expected_substr or expected_substr in found


def test_find_embedded_ats_url_none_when_missing():
    assert find_embedded_ats_url("<html><body>No board here</body></html>") is None
    assert find_embedded_ats_url(None) is None
