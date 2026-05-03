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

    # deepseek-v4-flash is a reasoning model — burns ~2000 reasoning tokens per batch.
    # 15 jobs per chunk keeps total completion tokens safely under 16k.
    CHUNK_SIZE = 15
    top_jobs = jobs[:50]

    effective_key = api_key or os.getenv("LLM_API_KEY", "")
    client_kwargs: dict[str, Any] = {"api_key": effective_key or "sk-placeholder"}
    base_url = os.getenv("LLM_BASE_URL", "")
    if base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)

    all_scored: list[ScoredJob] = []
    total_tokens = 0
    total_cost = 0.0

    for chunk_start in range(0, len(top_jobs), CHUNK_SIZE):
        chunk = top_jobs[chunk_start:chunk_start + CHUNK_SIZE]
        user_prompt = _build_user_prompt(chunk, profile, resume_summary)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=16000,
            )
        except Exception as exc:
            logger.error("LLM scoring failed (chunk %d): %s", chunk_start, exc)
            all_scored.extend(ScoredJob.from_job(j) for j in chunk)
            continue

        usage = response.usage
        tokens_used = (usage.prompt_tokens + usage.completion_tokens) if usage else 0
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        total_tokens += tokens_used
        total_cost += input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN

        raw_text = response.choices[0].message.content or ""
        scored_raw = _extract_json(raw_text)

        if not scored_raw:
            logger.warning("Failed to parse LLM JSON for chunk at %d — scoring 0", chunk_start)
            all_scored.extend(ScoredJob.from_job(j) for j in chunk)
            continue

        score_map: dict[int, dict] = {int(item["id"]): item for item in scored_raw if isinstance(item, dict) and "id" in item}

        for idx, job in enumerate(chunk, start=1):
            llm_result = score_map.get(idx, {})
            all_scored.append(ScoredJob.from_job(
                job,
                score=int(llm_result.get("score", 0)),
                reason=str(llm_result.get("reason", "")),
                skill_gap={
                    "have": llm_result.get("have", []),
                    "need": llm_result.get("need", []),
                    "gap": llm_result.get("gap", []),
                },
            ))

    logger.info("Scored %d jobs | tokens=%d | cost=$%.6f", len(all_scored), total_tokens, total_cost)
    return all_scored, total_tokens, total_cost


_VALIDATE_SYSTEM = (
    "You are a job data quality checker. "
    "Determine if a list of scraped items are real job postings or web page noise "
    "(navigation links, page titles, company names, marketing copy). "
    "Reply with JSON only: {\"valid\": bool, \"reason\": \"one sentence\"}"
)


async def validate_custom_scrape(
    jobs: list[Job],
    company_name: str,
    model: str = "",
    api_key: str = "",
) -> tuple[bool, str]:
    """
    LLM quality check for custom-scraped jobs.

    Returns (valid, reason). If LLM call fails, defaults to valid=True
    so we don't discard potentially good results on API errors.

    Only called when rule-based heuristics suggest results may be garbage
    (e.g. titles with no job keywords slipped through JSON extraction).
    """
    if not jobs:
        return False, "no jobs scraped"

    effective_key = api_key or os.getenv("LLM_API_KEY", "")
    if not effective_key:
        logger.warning("[validate] LLM_API_KEY not set — skipping validation")
        return True, "skipped (no api key)"

    _model = model or os.getenv("DISCOVER_MODEL", os.getenv("SCORING_MODEL", ""))
    client_kwargs: dict[str, Any] = {"api_key": effective_key}
    base_url = os.getenv("LLM_BASE_URL", "")
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)

    titles = "\n".join(f"- {j.title}" for j in jobs[:20])
    user_msg = (
        f"Company: {company_name}\n"
        f"Scraped titles:\n{titles}\n\n"
        "Are these actual job postings (roles like 'Senior Engineer', 'Product Manager') "
        "or website noise (nav links, page titles, marketing copy)?"
    )

    try:
        resp = await client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": _VALIDATE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=80,
        )
        raw = resp.choices[0].message.content or ""
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        parsed = json.loads(cleaned)
        valid = bool(parsed.get("valid", True))
        reason = str(parsed.get("reason", ""))
        logger.info("[validate] company=%r valid=%s reason=%s", company_name, valid, reason)
        return valid, reason
    except Exception as exc:
        logger.warning("[validate] LLM call failed for %r: %s — treating as valid", company_name, exc)
        return True, f"llm_error: {exc}"
