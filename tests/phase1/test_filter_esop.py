"""Tests for ESOP / equity detection."""
import pytest
from roleminer.pipeline.filter import detect_esop


def test_esop_keyword_detected():
    """'ESOP' keyword in JD → has_esop=True."""
    assert detect_esop("We offer ESOP to all employees from day one.") is True


def test_equity_keyword_detected():
    """'equity' keyword → has_esop=True."""
    assert detect_esop("Competitive equity package included.") is True


def test_stock_options_detected():
    """'stock options' → has_esop=True."""
    assert detect_esop("You will receive stock options as part of your comp.") is True


def test_rsu_detected():
    """'RSU' → has_esop=True."""
    assert detect_esop("We offer RSU grants on a 4-year vesting schedule.") is True


def test_rsus_plural_detected():
    """'RSUs' plural → has_esop=True."""
    assert detect_esop("RSUs are granted annually.") is True


def test_no_esop_signals():
    """JD with no equity signals → has_esop=False."""
    assert detect_esop("No additional benefits mentioned here.") is False


def test_empty_jd():
    """Empty JD → has_esop=False."""
    assert detect_esop("") is False


def test_case_insensitive():
    """Detection is case-insensitive."""
    assert detect_esop("Offers ESOP and equity participation.") is True
    assert detect_esop("Offers esop and Equity participation.") is True


def test_partial_word_not_matched():
    """'equitable' should NOT trigger equity detection (word boundary)."""
    # 'equity' would match in 'equitable' without word boundary — but ESOP_PATTERNS use \b
    # This tests that spurious matches don't occur for 'equity' embedded in other words.
    # Note: 'equity' IS in 'equitable' without \b, but our pattern uses \bequity\b
    result = detect_esop("An equitable work environment for all.")
    # 'equitable' does NOT contain the word 'equity' as a standalone — passes
    assert result is False
