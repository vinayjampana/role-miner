"""LLM-powered scrape strategy synthesis.

Takes the output from network_sniffer (discovered API or raw HTML) and uses
the project's existing OpenRouter/LLM setup to generate a structured
ScrapeStrategy JSON that can be persisted and reused for future scrape runs.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_STRATEGY_SYSTEM_PROMPT = (
    "You are a web scraping expert. Analyze the provided career page data and "
    "output a JSON scrape strategy. Return ONLY valid JSON — no explanation outside JSON."
)

_STRATEGY_USER_TEMPLATE = """Company: {company_name}
Data source: {data_type}

{data_content}

Output a JSON object with this exact schema:
{{
  "strategy_type": "api_intercept | dom_selector",
  "config": {{
    "url": "API endpoint or page URL",
    "method": "GET or POST",
    "payload_template": "Optional JSON payload for POST (null if GET)",
    "headers": {{}},
    "result_path": "Dot-notation path to the array of jobs (for APIs) or CSS selector for job cards (for DOM)",
    "mapping": {{
      "title": "JSON key or CSS selector for job title",
      "url": "JSON key or CSS selector for job URL",
      "location": "JSON key or CSS selector for job location"
    }}
  }}
}}

Rules:
- If the data contains a discovered JSON API (type=api), set strategy_type to "api_intercept".
- If the data is raw HTML (type=html), set strategy_type to "dom_selector" and provide CSS selectors.
- For api_intercept, result_path uses dot notation (e.g. "data.jobs" or "results").
- For dom_selector, result_path is a CSS selector matching individual job card elements.
- mapping values are either JSON object keys (for api_intercept) or CSS selectors (for dom_selector).
- Only include headers that are actually needed (e.g. Content-Type, Authorization).
- Be specific with selectors to avoid false positives."""


def _extract_json(text: str) -> dict | None:
    cleaned = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return None


def _validate_strategy(strategy: dict) -> dict | None:
    if "strategy_type" not in strategy or "config" not in strategy:
        return None
    st = strategy["strategy_type"]
    if st not in ("api_intercept", "dom_selector"):
        return None
    config = strategy["config"]
    if not isinstance(config, dict):
        return None
    if "url" not in config or "result_path" not in config:
        return None
    if "mapping" not in config or not isinstance(config["mapping"], dict):
        return None
    mapping = config["mapping"]
    if "title" not in mapping:
        return None
    return strategy


async def generate_scrape_strategy(
    company_name: str,
    sniffer_data: dict,
) -> dict | None:
    """Use LLM to generate a ScrapeStrategy from sniffer output.

    Args:
        company_name: Name of the company (for context).
        sniffer_data: Output from sniff_career_page — either
            {"type": "api", "api_url": ..., ...} or
            {"type": "html", "html": "..."}.

    Returns:
        Validated strategy dict or None on failure.
    """
    api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        logger.warning("[strategy-builder] LLM_API_KEY not set — cannot generate strategy")
        return None

    base_url = os.getenv("LLM_BASE_URL", "")
    model = os.getenv("DISCOVER_MODEL", os.getenv("SCORING_MODEL", "tencent/hy3-preview:free"))

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)

    data_type = sniffer_data.get("type", "unknown")

    if data_type == "api":
        data_content = (
            f"Discovered API URL: {sniffer_data.get('api_url', '')}\n"
            f"Method: {sniffer_data.get('method', 'GET')}\n"
            f"Headers: {json.dumps(sniffer_data.get('headers', {}))}\n"
            f"Post data: {sniffer_data.get('post_data') or 'None'}\n"
            f"Sample response (first 8000 chars):\n{str(sniffer_data.get('sample', ''))[:8000]}"
        )
    else:
        html = sniffer_data.get("html", "")
        data_content = f"Raw HTML (stripped of script/style tags):\n{html[:8000]}"

    user_prompt = _STRATEGY_USER_TEMPLATE.format(
        company_name=company_name,
        data_type=data_type,
        data_content=data_content,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _STRATEGY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception as exc:
        logger.error("[strategy-builder] LLM call failed for %r: %s", company_name, exc)
        return None

    raw_text = response.choices[0].message.content or ""
    strategy = _extract_json(raw_text)
    if not strategy:
        logger.warning("[strategy-builder] failed to parse LLM JSON for %r", company_name)
        return None

    validated = _validate_strategy(strategy)
    if not validated:
        logger.warning("[strategy-builder] strategy validation failed for %r: %s", company_name, json.dumps(strategy)[:200])
        return None

    logger.info(
        "[strategy-builder] generated strategy for %r type=%s url=%s",
        company_name, validated["strategy_type"], validated["config"].get("url", ""),
    )
    return validated
