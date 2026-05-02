# RoleMiner — CLAUDE.md

India-first job discovery tool. Scrapes 5 ATS sources, scores against candidate profile, surfaces ranked shortlist via FastAPI + React.

## Project Goal

Personal tool for Vinay to find relevant senior engineering roles in India. Not a SaaS product — optimize for correctness and cost, not scale.

## Stack

- Python 3.11+ · FastAPI · SQLite · ChromaDB · HTTPX · scikit-learn (TF-IDF fallback)
- React 18 · Vite · TypeScript · React Query · Recharts · Tailwind
- Docker Compose (local + VPS deploy)
- LLM: any OpenAI-compatible API via `LLM_API_KEY` + `LLM_BASE_URL` env vars
- Embeddings: `nvidia/llama-nemotron-embed-vl-1b-v2:free` via OpenRouter (`EMBED_API_KEY`)

## Key Constraints

- **India salary always LPA** — never USD internally
- **Never store full JDs** — company metadata only, fresh JDs fetched each run
- **Dedup by URL** before scoring — same job appears on multiple sources
- **Wellfound MUST use India location filter** — without it skews US-heavy
- **Naukri**: email parse first, browser scrape fallback only if coverage insufficient
- **Service company filter is rule-based**, not LLM
- **Single LLM call per run** — batch score top 50 jobs, structured JSON output
- All scrapers return same `Job` dataclass — decoupled from pipeline
- **LLM config via env**: `LLM_API_KEY`, `LLM_BASE_URL`, `SCORING_MODEL` — no hardcoded provider
- **run_events table**: every pipeline step logged to SQLite with timing + errors — drives SSE stream and RunLogs UI
- **Scraper freshness**: `SCRAPER_FRESHNESS_HOURS` (default 24h) — skip companies scraped recently; emits `scraper_skipped` event
- **Stale run cleanup**: on server startup, runs stuck in `running` status → auto-marked `failed`
- **Company auto-discovery**: job URLs parsed for ATS patterns (greenhouse/lever/ashby) after each scrape run; new companies inserted automatically

## Directory Layout

```
main.py                    # CLI: bootstrap | run | serve
config.py                  # all env vars + paths
search_profile.yaml        # user-edited job preferences
roleminer/
├── scrapers/              # one file per ATS source
├── registry/
│   ├── db.py              # SQLite CRUD + cleanup_stale_runs
│   ├── vector_store.py    # ChromaDB: companies + jobs collections
│   └── career_finder.py   # 4-step career URL discovery (cache→heuristic→search→LLM)
├── pipeline/
│   ├── embedder.py        # OpenRouter embed client + embed_batched()
│   ├── ranker.py          # semantic rank if EMBED_API_KEY set, else TF-IDF
│   ├── filter.py
│   ├── role_filter.py
│   └── scorer.py
└── api/
    ├── main.py            # FastAPI app + lifespan (stale run cleanup)
    ├── models.py          # Pydantic models incl. DiscoverRequest/DiscoverResult
    └── routes/
        ├── companies.py   # GET /companies + POST /companies/discover (SSE)
        ├── runs.py        # run management + trigger
        └── stream.py      # SSE pipeline event stream
frontend/src/
├── views/                 # Dashboard · RunLogs · Companies
├── components/            # JobCard · JobDetail · RunEventStream
├── lib/datetime.ts        # IST formatting (formatRunStartedAt, formatEventLogTime)
└── api/client.ts          # typed API client incl. discoverCompanies()
```

## Pipeline events (run_events table)

Every step emits structured events to SQLite + SSE queue:

| event_type | When | Key data fields |
|---|---|---|
| `scrape_start` | Before scraping loop | `total_sources`, `companies[]`, `freshness_hours` |
| `scraper_start` | Before each company | `company`, `ats` |
| `scraper_done` | After each company | `jobs_fetched`, `duration_ms`, `error` |
| `scraper_skipped` | Company is fresh | `last_scraped_hours_ago`, `freshness_hours` |
| `discover_done` | After URL auto-discovery | `new_companies`, `names[]` |
| `filter_done` | After rule filter | `total_in/out`, `dropped_*` counts |
| `role_filter_done` | After role filter | `total_in/out`, `dropped`, `sample_dropped[]` |
| `embed_done` | After ChromaDB upsert | `jobs_embedded`, `model` |
| `rank_done` | After ranking | `total_ranked`, `top_scores[]`, `sent_to_scorer` |
| `score_done` | After LLM scoring | `jobs_scored`, `tokens_used`, `cost_usd`, `score_distribution` |
| `error` | On any exception | `step`, `company`, `error`, `traceback` |

## Config env vars

| Var | Default | Purpose |
|---|---|---|
| `LLM_API_KEY` | — | Scoring LLM + company discover LLM |
| `LLM_BASE_URL` | — | OpenAI-compatible base URL |
| `SCORING_MODEL` | `gemini-3-flash` | Model for job scoring |
| `EMBED_API_KEY` | falls back to `LLM_API_KEY` | Embedding API key |
| `EMBED_BASE_URL` | `https://openrouter.ai/api/v1` | Embedding API base URL |
| `EMBED_MODEL` | `nvidia/llama-nemotron-embed-vl-1b-v2:free` | Embedding model |
| `DISCOVER_MODEL` | `tencent/hy3-preview:free` | Model for career URL discovery |
| `BRAVE_SEARCH_API_KEY` | — | Optional Brave Search for discover flow |
| `SCRAPER_FRESHNESS_HOURS` | `24` | Skip companies scraped within this window |
| `PROXY_URL` | — | Optional HTTP proxy for scrapers |

## Running Locally

```bash
# CLI only
python main.py bootstrap    # seed company registry + embed companies
python main.py run          # scrape → filter → embed → rank → score
python main.py serve        # start FastAPI on :8000

# Full stack
docker compose up           # API on :8000, frontend on :3000
cd frontend && npm run dev  # dev mode: proxies /api → localhost:8000
```

## Testing Convention

- Each phase has a `tests/phaseN/` directory
- Use `pytest` with real HTTP calls where safe (Greenhouse, Lever APIs are public)
- Mock only: Playwright, external LLM calls, proxy sessions
- Run with: `pytest tests/phaseN/ -v`

## Cost Budget

- < $0.002 per run (< ₹0.17)
- Bootstrap (one-time): < $0.001
- Embeddings: free tier (OpenRouter, nvidia model)
- Company discovery: free tier (tencent/hy3-preview)
