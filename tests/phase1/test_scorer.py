"""Tests for the LLM scorer — mocked OpenAI client."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from roleminer.scrapers.base import Job, ScoredJob
from roleminer.pipeline.scorer import score_jobs, _extract_json


# ---------------------------------------------------------------------------
# Unit tests for JSON extraction
# ---------------------------------------------------------------------------

def test_extract_json_bare_array():
    raw = '[{"id":1,"score":8,"reason":"good fit","have":["React"],"need":[],"gap":[]}]'
    result = _extract_json(raw)
    assert len(result) == 1
    assert result[0]["score"] == 8


def test_extract_json_with_code_fence():
    raw = '```json\n[{"id":1,"score":7,"reason":"ok","have":[],"need":[],"gap":[]}]\n```'
    result = _extract_json(raw)
    assert len(result) == 1
    assert result[0]["score"] == 7


def test_extract_json_with_preamble():
    raw = 'Here is the result:\n[{"id":1,"score":5,"reason":"avg","have":[],"need":[],"gap":[]}]'
    result = _extract_json(raw)
    assert len(result) == 1


def test_extract_json_invalid_returns_empty():
    result = _extract_json("This is not JSON at all.")
    assert result == []


# ---------------------------------------------------------------------------
# Integration test with mocked OpenAI
# ---------------------------------------------------------------------------

def _make_job(idx: int) -> Job:
    return Job(
        title=f"Senior Engineer {idx}",
        company=f"Company {idx}",
        url=f"https://example.com/job/{idx}",
        date_posted=(datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat(),
        location="Bangalore",
        source="greenhouse",
        jd_text="React TypeScript Node.js experience required.",
    )


_PROFILE = {
    "skills": ["React", "TypeScript", "Node.js"],
    "locations": ["Bangalore"],
    "salary_min_lpa": 30,
    "work_mode": ["remote", "hybrid"],
    "notice_days": 60,
}

_RESUME = "Senior full-stack engineer with 8+ years in React, TypeScript, Node."


def _make_mock_response(content: str):
    """Build a mock openai ChatCompletion response."""
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 500
    mock_usage.completion_tokens = 100

    mock_choice = MagicMock()
    mock_choice.message.content = content

    mock_resp = MagicMock()
    mock_resp.usage = mock_usage
    mock_resp.choices = [mock_choice]
    return mock_resp


@patch("roleminer.pipeline.scorer.AsyncOpenAI")
async def test_score_jobs_returns_scored_jobs(mock_openai_cls):
    """Scorer returns correct ScoredJob list when LLM returns valid JSON."""
    jobs = [_make_job(i) for i in range(1, 4)]

    llm_json = json.dumps([
        {"id": 1, "score": 8, "reason": "strong React background", "have": ["React"], "need": ["Rust"], "gap": ["Rust"]},
        {"id": 2, "score": 6, "reason": "decent fit", "have": ["TypeScript"], "need": [], "gap": []},
        {"id": 3, "score": 4, "reason": "weak match", "have": [], "need": ["Go"], "gap": ["Go"]},
    ])

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(llm_json))
    mock_openai_cls.return_value = mock_client

    scored, tokens, cost = await score_jobs(
        jobs=jobs,
        profile=_PROFILE,
        resume_summary=_RESUME,
        model="gpt-4o-mini",
        api_key="sk-test",
    )

    assert len(scored) == 3
    assert isinstance(scored[0], ScoredJob)

    assert scored[0].score == 8
    assert scored[0].reason == "strong React background"
    assert scored[0].skill_gap["have"] == ["React"]
    assert scored[0].skill_gap["gap"] == ["Rust"]

    assert scored[1].score == 6
    assert scored[2].score == 4

    assert tokens > 0
    assert cost > 0.0


@patch("roleminer.pipeline.scorer.AsyncOpenAI")
async def test_score_jobs_graceful_on_json_error(mock_openai_cls):
    """Scorer assigns score=0 to all jobs when LLM returns unparseable JSON."""
    jobs = [_make_job(1), _make_job(2)]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_mock_response("Sorry, I cannot help with that.")
    )
    mock_openai_cls.return_value = mock_client

    scored, tokens, cost = await score_jobs(
        jobs=jobs, profile=_PROFILE, resume_summary=_RESUME, model="gpt-4o-mini", api_key="sk-test"
    )

    assert len(scored) == 2
    for s in scored:
        assert s.score == 0


@patch("roleminer.pipeline.scorer.AsyncOpenAI")
async def test_score_jobs_empty_input(mock_openai_cls):
    """Empty job list returns empty list without calling LLM."""
    scored, tokens, cost = await score_jobs(
        jobs=[], profile=_PROFILE, resume_summary=_RESUME, model="gpt-4o-mini", api_key="sk-test"
    )
    assert scored == []
    assert tokens == 0
    assert cost == 0.0
    mock_openai_cls.assert_not_called()


@patch("roleminer.pipeline.scorer.AsyncOpenAI")
async def test_score_jobs_caps_at_50(mock_openai_cls):
    """Scorer only sends first 50 jobs to LLM regardless of input size."""
    jobs = [_make_job(i) for i in range(1, 101)]  # 100 jobs

    # Return scores for only 50
    llm_json = json.dumps([
        {"id": i, "score": 5, "reason": "ok", "have": [], "need": [], "gap": []}
        for i in range(1, 51)
    ])

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(llm_json))
    mock_openai_cls.return_value = mock_client

    scored, _, _ = await score_jobs(
        jobs=jobs, profile=_PROFILE, resume_summary=_RESUME, model="gpt-4o-mini", api_key="sk-test"
    )

    assert len(scored) == 50
