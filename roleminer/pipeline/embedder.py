"""OpenRouter embedding client — nvidia/llama-nemotron-embed-vl-1b-v2:free."""
import logging
from typing import Literal

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None
_BATCH_SIZE = 50


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=config.EMBED_BASE_URL,
            api_key=config.EMBED_API_KEY,
        )
    return _client


def reset_client() -> None:
    """Drop cached OpenAI client so the next embed uses fresh config (e.g. new API key)."""
    global _client
    _client = None


def embed(texts: list[str], input_type: Literal["query", "passage"] = "passage") -> list[list[float]]:
    """Return embeddings for texts. input_type='query' for profile, 'passage' for docs."""
    if not texts:
        return []
    client = _get_client()
    resp = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
    ordered = sorted(resp.data, key=lambda x: x.index)
    return [item.embedding for item in ordered]


def embed_batched(texts: list[str], input_type: Literal["query", "passage"] = "passage") -> list[list[float]]:
    """Embed in batches of _BATCH_SIZE to avoid API limits."""
    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        results.extend(embed(batch, input_type=input_type))
        logger.debug("embedded batch %d-%d", i, i + len(batch))
    return results


def is_available() -> bool:
    return bool(config.EMBED_API_KEY)
