"""Static company registry — single source of truth for V1."""
import json
import logging

import config

logger = logging.getLogger(__name__)


def load_companies() -> list[dict]:
    """Load companies from static JSON registry."""
    path = config.COMPANIES_JSON_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "Company registry JSON not found at %s — set ROLEMINER_COMPANIES_JSON if mounted elsewhere",
            path,
        )
        return []
    except OSError as exc:
        logger.warning("Cannot read company registry at %s: %s", path, exc)
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in company registry %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        return []
    return data
