"""Tests for notice period compatibility detection."""
import pytest
from roleminer.pipeline.filter import detect_notice_compatible


def test_immediate_joiner_with_notice_incompatible():
    """JD requiring immediate joiner + candidate notice > 0 → not compatible."""
    jd = "We are looking for an immediate joiner to join our team ASAP."
    assert detect_notice_compatible(jd, notice_days=60) is False


def test_no_immediate_requirement_compatible():
    """JD without immediate requirement → always compatible regardless of notice."""
    jd = "We are hiring a senior engineer with strong TypeScript skills."
    assert detect_notice_compatible(jd, notice_days=60) is True


def test_immediate_joiner_with_zero_notice_compatible():
    """JD requiring immediate joiner + candidate notice = 0 → compatible."""
    jd = "This role requires an immediate joiner only."
    assert detect_notice_compatible(jd, notice_days=0) is True


def test_join_immediately_variant():
    """'join immediately' phrase → not compatible when notice > 0."""
    jd = "Please note candidates must join immediately."
    assert detect_notice_compatible(jd, notice_days=30) is False


def test_no_notice_period_phrase():
    """'no notice period' phrase → not compatible when notice > 0."""
    jd = "Only candidates with no notice period should apply."
    assert detect_notice_compatible(jd, notice_days=15) is False


def test_empty_jd_compatible():
    """Empty JD → compatible (no restriction found)."""
    assert detect_notice_compatible("", notice_days=60) is True


def test_negative_notice_always_compatible():
    """Negative notice_days treated as 0 → always compatible."""
    jd = "Immediate joiner required."
    assert detect_notice_compatible(jd, notice_days=-1) is True
