"""OpenRouter embedding client — nvidia/llama-nemotron-embed-vl-1b-v2:free."""
import logging
from typing import Literal

import httpx
from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None
_BATCH_SIZE = 50


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = (config.EMBED_API_KEY or "").strip()
        _client = OpenAI(
            base_url=(config.EMBED_BASE_URL or "").strip() or "https://openrouter.ai/api/v1",
            api_key=key,
        )
    return _client


def reset_client() -> None:
    """Drop cached OpenAI client so the next embed uses fresh config (e.g. new API key)."""
    global _client
    _client = None


def _embed_openrouter_http(texts: list[str]) -> list[list[float]]:
    """Direct POST — some OpenRouter models return bodies the OpenAI SDK post-parser mishandles."""
    base = (config.EMBED_BASE_URL or "").strip().rstrip("/") or "https://openrouter.ai/api/v1"
    url = f"{base}/embeddings"
    key = (config.EMBED_API_KEY or "").strip()
    payload = {
        "model": config.EMBED_MODEL,
        "input": texts,
        "encoding_format": "float",
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        body = r.json()
    data = body.get("data") or []
    if not data:
        logger.error(
            "Embeddings HTTP response had no data; keys=%s snippet=%s",
            list(body.keys()),
            str(body)[:800],
        )
        raise ValueError("OpenRouter embeddings: empty data array in JSON response")
    ordered = sorted(data, key=lambda x: x.get("index", 0))
    out: list[list[float]] = []
    for item in ordered:
        vec = item.get("embedding")
        if vec is None:
            continue
        out.append([float(x) for x in vec])
    if len(out) != len(texts):
        logger.warning(
            "Embedding count mismatch: inputs=%d outputs=%d model=%s",
            len(texts),
            len(out),
            config.EMBED_MODEL,
        )
    return out


def embed(texts: list[str], input_type: Literal["query", "passage"] = "passage") -> list[list[float]]:
    """Return embeddings for texts. input_type='query' for profile, 'passage' for docs."""
    if not texts:
        return []
    client = _get_client()
    # SDK defaults to encoding_format=base64; OpenRouter often works reliably with float JSON.
    try:
        resp = client.embeddings.create(
            model=config.EMBED_MODEL,
            input=texts,
            encoding_format="float",
        )
    except ValueError as exc:
        if "No embedding data received" in str(exc):
            logger.warning("SDK embed returned no data; retrying OpenRouter via HTTP (%s)", exc)
            return _embed_openrouter_http(texts)
        raise
    if not resp.data:
        logger.warning("SDK embed: empty resp.data; retrying via HTTP")
        return _embed_openrouter_http(texts)
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
    return bool((config.EMBED_API_KEY or "").strip())
