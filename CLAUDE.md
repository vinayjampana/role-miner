# RoleMiner — CLAUDE.md

India-first job discovery tool. Scrapes multiple ATS sources (Greenhouse, Lever, Ashby, Cutshort, Workday, SmartRecruiters, custom/custom_api), scores against candidate profile, surfaces ranked shortlist via FastAPI + React.

## Project Goal

Personal tool for Vinay to find relevant senior engineering roles in India. Not a SaaS product — optimize for correctness and cost, not scale.

## Stack

- Python 3.11+ · FastAPI · SQLite · ChromaDB · HTTPX · Playwright (custom careers + ATS browser-detect) · scikit-learn (TF-IDF fallback)
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
- **Single LLM call per run** — batch score top 50 jobs, structured JSON output; **plus** `validate_custom_scrape()` cheap call (≤80 tokens, `DISCOVER_MODEL`) after custom Playwright scrape to reject nav/marketing garbage
- All scrapers return same `Job` dataclass — decoupled from pipeline
- **Custom scraper strategy order**: (0) XHR network intercept (SPA/React) → (1) embedded JSON (`__NEXT_DATA__`) → (2) job card DOM selectors → (3) link heuristics → zero-job fallback: `find_redirect_via_cta` to discover real portal URL and update DB
- **`_looks_like_job_title`**: whole-word regex (`_JOB_KEYWORD_RE`), max 10 words, `_MARKETING_RE` + `_CONTENT_SUFFIX_RE` guards — no substring matching; ambiguous single words (product/data/sales) require a qualifying role word
- **browser_detect Signal 5**: `_JOB_PORTAL_RE` matches 20+ unsupported ATS portals (trakstar, workable, breezy, recruitee, iCIMS, Taleo, BambooHR, etc.) in `<a href>` scan — updates `careers_url` to real listing page even for unknown ATS
- **LLM config via env**: `LLM_API_KEY`, `LLM_BASE_URL`, `SCORING_MODEL` — no hardcoded provider
- **run_events table**: every pipeline step logged to SQLite with timing + errors — drives SSE stream and RunLogs UI; **dedup_done** + filter/rank/score events include **capped job snapshots** (`jobs` / `jobs_passed` / `jobs_ranked` / `jobs_scored_detail`) for debugging; server logs **`[pipeline] run_id=…`** summaries per step
- **Scraper freshness**: `SCRAPER_FRESHNESS_HOURS` (default 24h) — skip companies scraped recently; emits `scraper_skipped` event
- **Stale run cleanup**: on server startup, runs stuck in `running` status → auto-marked `failed`
- **Company auto-discovery**: job URLs parsed for ATS patterns (greenhouse/lever/ashby) after each scrape run; new companies inserted automatically
- **Job shortlist**: `GET /jobs/latest` uses **`get_jobs_for_profile`** — all **completed** runs for the user’s **active** `search_profile_id` (plus legacy runs with `NULL` profile); **dedupe by `job_url`**; keep **max(score)** per URL (tie-break: latest run); **`min_score` query default 6**
- **Tracker**: `job_status` per user + URL — statuses include `new`, `clicked`, `saved`, `archived`, `applied`, `interviewing`, `rejected`, `dismissed`; `POST /jobs/status`, `POST /jobs/click` (promote `new` → `clicked`)
- **API identity**: optional **`X-User-Id`** header; omit or `0` → default user (`ensure_default_user_id`)

## Directory Layout

```
main.py                    # CLI: bootstrap | run | serve | reset-scrape
config.py                  # all env vars + paths
search_profile.yaml        # user-edited job preferences
roleminer/
├── scrapers/              # one file per ATS source
├── registry/
│   ├── db.py              # SQLite CRUD + cleanup_stale_runs + users/profiles + get_jobs_for_profile
│   ├── vector_store.py    # ChromaDB: companies + jobs collections
│   ├── ats_detect.py      # ATS detect + embedded careers URLs in HTML (+ SmartRecruiters)
│   ├── job_api_discover.py # proprietary job JSON API discovery from JS chunks (+ careers.* fallback)
│   ├── browser_detect.py  # Playwright ATS fallback (network + DOM + hrefs)
│   └── career_finder.py   # 4-step career URL discovery (cache→heuristic→search→LLM)
├── pipeline/
│   ├── embedder.py        # OpenRouter embed client + embed_batched()
│   ├── ranker.py          # semantic rank if EMBED_API_KEY set, else TF-IDF
│   ├── filter.py
│   ├── role_filter.py
│   └── scorer.py
└── api/
    ├── main.py            # FastAPI app + lifespan (stale run cleanup)
    ├── auth.py            # X-User-Id → CurrentUser (active_profile_id)
    ├── models.py          # Pydantic models incl. DiscoverRequest/DiscoverResult
    └── routes/
        ├── jobs.py        # GET /jobs/latest|run|tracked, POST /jobs/status|click
        ├── users.py       # GET/POST /users, GET /me
        ├── preferences.py # profile + resume + settings
        ├── companies.py   # GET /companies + POST /companies/discover (SSE) + POST /companies/{id}/scrape
        ├── runs.py        # run management + trigger
        ├── stats.py
        └── stream.py      # SSE pipeline event stream
frontend/src/
├── views/                 # Dashboard · Tracker · RunLogs · Companies · Settings
├── auth/                  # user id for client (X-User-Id)
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
| `dedup_done` | After dedup by URL (post-scrape) | `total_in`, `total_out`, `removed`, `jobs` `{total, truncated, items[]}` |
| `filter_done` | After rule filter | `total_in/out`, `dropped_*`, `sample_dropped[]`, `jobs_passed` snapshot |
| `role_filter_done` | After role filter | `total_in/out`, `dropped`, `sample_dropped[]` (incl. `url`), `jobs_passed` snapshot |
| `embed_done` | After ChromaDB upsert | `jobs_embedded`, `model` |
| `rank_done` | After ranking | `total_ranked`, `top_scores[]`, `sent_to_scorer`, `jobs_ranked` (incl. `rank_score`) |
| `score_done` | After LLM scoring | `jobs_scored`, `tokens_used`, `cost_usd`, `score_distribution`, `top_jobs`, `jobs_scored_detail` |
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
| `SCRAPER_DELAY_MIN` | `5` | Min seconds between company scrapes (anti-ban) |
| `SCRAPER_DELAY_MAX` | `15` | Max seconds between company scrapes (anti-ban) |
| `SCRAPER_PAGINATION_DELAY_MIN` | `2` | Min seconds between pagination requests |
| `SCRAPER_PAGINATION_DELAY_MAX` | `6` | Max seconds between pagination requests |
| `PROXY_URL` | — | Optional HTTP proxy for scrapers |

## Running Locally

```bash
# CLI only
python main.py bootstrap     # seed company registry + embed companies
python main.py run           # scrape → filter → embed → rank → score
python main.py serve         # start FastAPI on :8000
python main.py reset-scrape  # clear last_scraped_at (force full re-scrape next run)

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
