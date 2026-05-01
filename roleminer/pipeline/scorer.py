"""LLM batch scorer — single API call per run."""
import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

from roleminer.scrapers.base import Job, ScoredJob

logger = logging.getLogger(__name__)

# gpt-4o-mini pricing ($/token)
_INPUT_COST_PER_TOKEN = 0.00000015
_OUTPUT_COST_PER_TOKEN = 0.0000006

_SYSTEM_PROMPT = (
    "You are a senior technical recruiter. "
    "Score job fit for an India-based candidate. "
    "Return a JSON array only. No explanation outside JSON."
)


def _build_user_prompt(jobs: list[Job], profile: dict, resume_summary: str) -> str:
    stack = ", ".join(profile.get("skills", []))
    notice_days = profile.get("notice_days", 0)

    lines = [
        "CANDIDATE PROFILE:",
        resume_summary.strip(),
        f"Notice period: {notice_days} days | Stack: {stack}",
        "",
        "JOBS (score each 0-10):",
    ]

    for idx, job in enumerate(jobs, start=1):
        jd_preview = job.jd_text[:200].strip() if job.jd_text else ""
        line = f"[{idx}] {job.title} | {job.company} | {job.location} | {job.funding_stage}"
        lines.append(line)
        if jd_preview:
            lines.append(f"    {jd_preview}")

    lines.append("")
    lines.append(
        'Return JSON array:\n'
        '[{"id":1,"score":9,"reason":"one line","have":["React"],"need":["Rust"],"gap":["Rust"]}]'
    )
    return "\n".join(lines)


def _extract_json(text: str) -> list[dict]:
    """
    Extract a JSON array from the LLM response.
    Handles code fences like ```json ... ``` and bare arrays.
    """
    # Strip code fences
    cleaned = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()

    # Try direct parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find first [...] block
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


async def score_jobs(
    jobs: list[Job],
    profile: dict,
    resume_summary: str,
    model: str = "gpt-4o-mini",
    api_key: str = "",
) -> tuple[list[ScoredJob], int, float]:
    """
    Score top 50 jobs with a single LLM API call.

    Args:
        jobs: Jobs to score (caller should pass at most 50)
        profile: Loaded search_profile dict
        resume_summary: Plain-text summary of candidate
        model: OpenAI-compatible model name
        api_key: API key (falls back to OPENAI_API_KEY env var)

    Returns:
        (scored_jobs, tokens_used, cost_usd)
        On error: all jobs scored 0, tokens=0, cost=0.0
    """
    if not jobs:
        return [], 0, 0.0

    batch = jobs[:50]

    effective_key = api_key or os.getenv("OPENAI_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")

    # DeepSeek uses the same OpenAI client with a different base_url
    client_kwargs: dict[str, Any] = {"api_key": effective_key or "sk-placeholder"}
    if "deepseek" in model.lower():
        client_kwargs["base_url"] = "https://api.deepseek.com/v1"

    client = AsyncOpenAI(**client_kwargs)

    user_prompt = _build_user_prompt(batch, profile, resume_summary)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except Exception as exc:
        logger.error("LLM scoring failed: %s", exc)
        return [ScoredJob.from_job(j) for j in batch], 0, 0.0

    usage = response.usage
    tokens_used = (usage.prompt_tokens + usage.completion_tokens) if usage else 0
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    cost_usd = input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN

    raw_text = response.choices[0].message.content or ""
    scored_raw = _extract_json(raw_text)

    if not scored_raw:
        logger.warning("Failed to parse LLM JSON response — assigning score 0 to all")
        return [ScoredJob.from_job(j) for j in batch], tokens_used, cost_usd

    # Build id → result map (LLM uses 1-based ids)
    score_map: dict[int, dict] = {}
    for item in scored_raw:
        if isinstance(item, dict) and "id" in item:
            score_map[int(item["id"])] = item

    scored_jobs: list[ScoredJob] = []
    for idx, job in enumerate(batch, start=1):
        llm_result = score_map.get(idx, {})
        score = int(llm_result.get("score", 0))
        reason = str(llm_result.get("reason", ""))
        skill_gap = {
            "have": llm_result.get("have", []),
            "need": llm_result.get("need", []),
            "gap": llm_result.get("gap", []),
        }
        scored_jobs.append(ScoredJob.from_job(job, score=score, reason=reason, skill_gap=skill_gap))

    logger.info(
        "Scored %d jobs | tokens=%d | cost=$%.6f",
        len(scored_jobs), tokens_used, cost_usd,
    )
    return scored_jobs, tokens_used, cost_usd
