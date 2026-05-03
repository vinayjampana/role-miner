# Integrations

## LLM (Scoring + Discovery)

Provider-agnostic via OpenAI-compatible API.

| Env Var | Purpose | Default |
|---|---|---|
| `LLM_API_KEY` | Scoring + company discovery | required |
| `LLM_BASE_URL` | OpenAI-compatible base URL | required |
| `SCORING_MODEL` | Job scoring model | `gemini-3-flash` |
| `DISCOVER_MODEL` | Career URL discovery + custom scrape validation | `tencent/hy3-preview:free` |

**Scoring call**: single batch, top 50 jobs, structured JSON `{job_url, score, reason}`.
**Discovery call**: `validate_custom_scrape()` — ≤80 tokens, cheap model, rejects nav/marketing garbage.

## Embeddings

| Env Var | Purpose | Default |
|---|---|---|
| `EMBED_API_KEY` | Embedding API key (falls back to `LLM_API_KEY`) | — |
| `EMBED_BASE_URL` | Embedding API base URL | `https://openrouter.ai/api/v1` |
| `EMBED_MODEL` | Embedding model | `nvidia/llama-nemotron-embed-vl-1b-v2:free` |

Client: `roleminer/pipeline/embedder.py` → `embed_batched()`.
Store: ChromaDB via `roleminer/registry/vector_store.py`.
Fallback: TF-IDF (`sklearn`) if `EMBED_API_KEY` absent.

## Brave Search

| Env Var | Purpose |
|---|---|
| `BRAVE_SEARCH_API_KEY` | Optional; used in `career_finder.py` step 3 (search fallback) |

Used when heuristic + cache miss; searches for company careers page URL.

## Proxy

| Env Var | Purpose |
|---|---|
| `PROXY_URL` | Optional HTTP proxy for all scrapers |

Passed through HTTPX/Playwright sessions.

## ChromaDB

Local persistent store at `roleminer/registry/chroma/`.
Two collections: `companies` (for career URL semantic search) + `jobs` (for ranking).

## SQLite

Local file: `roleminer/registry/roleminer.db`.
Tables: `companies`, `runs`, `run_events`, `jobs`, `users`, `search_profiles`, `job_status`.
