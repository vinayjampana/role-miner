# RoleMiner

Personal job discovery tool for senior engineering roles in India. Scrapes multiple sources, scores against your profile, surfaces a ranked shortlist via CLI or React dashboard.

## Recent updates (since last release commit)

- **Custom scraper — SPA network intercept**: Playwright now intercepts XHR/fetch responses during page load (Strategy 0) to capture job API calls from React/Next.js career pages (e.g. Upstox). Captures same-domain JSON responses, replays via `page.request`, parses with `_extract_job_items`. Runs before DOM strategies.
- **Custom scraper — redirect discovery**: When 0 jobs scraped, `find_redirect_via_cta` uses Playwright to find the real job portal URL — Phase 1 scans `<a href>` links by CTA text or known portal domain (`_JOB_PORTAL_RE`); Phase 2 clicks buttons and captures popup/navigation URL. Updates `careers_url` in DB for future runs. Handles pages like `whatfix.com/careers` → `whatfix101.hire.trakstar.com`.
- **browser_detect Signal 5**: Extends `detect_ats_with_browser` to capture hrefs to 20+ unsupported job portals (trakstar, workable, breezy, recruitee, iCIMS, Taleo, BambooHR, teamtailor, Keka, Darwinbox, etc.) even when no known ATS is detected. Updates `careers_url` in DB so next scrape targets the real listing page.
- **`_looks_like_job_title` rewrite**: Whole-word regex (`_JOB_KEYWORD_RE`) instead of substring matching — fixes false positives like "productivity" → "product", "Managers" → "manager", "analytics" → "analyst". Adds word-count cap (> 10 words rejected), `_MARKETING_RE` (kills testimonials/CTAs), `_CONTENT_SUFFIX_RE` (kills "Analyst Reports", "Developer Hub"). Tested against 27 pass/fail cases.
- **`_walk_json_for_jobs` fix**: Now applies `_looks_like_job_title` before emitting a job from Next.js page metadata — stops page titles like "Home", "Whatfix" from becoming job entries.
- **LLM scrape validation**: `validate_custom_scrape()` in `scorer.py` — cheap LLM call (≤80 tokens, uses `DISCOVER_MODEL` free tier) after custom Playwright scrape; detects nav/marketing garbage that slips past rules; fails open (valid=True) on API error.
- **Custom career sites**: Playwright-based DOM scraper with pagination; **proprietary JSON APIs** discovered from JS bundles (`custom_api` ATS type), including split-bundle heuristics (e.g. Cars24 via `careers.{domain}` fallback and `*.team` API hosts). `job_api_discover` module; Docker image installs Playwright browsers.
- **SmartRecruiters**: New scraper + ATS detection; **Freshworks** seed uses `https://careers.smartrecruiters.com/Freshworks`.
- **Resolve / detect**: JS chunk scan for embedded ATS URLs; **Playwright fallback** (`browser_detect`) when static HTML has no board URL; Workday human URLs normalized to CXS where applicable.
- **Registry seed**: **Darwinbox** added (`custom`, Darwinbox careers URL); **Razorpay** and other seed fixes as in `db.py`.
- **Run logs**: New **`dedup_done`** event; rule filter, role filter, rank, and score events include **capped job snapshots** (title, company, URL; rank/score where relevant). Structured **`logger.info`** summaries per step. RunLogs UI: **Dedup** pipeline step, expandable job tables, live SSE merges so snapshots update before refetch; stream lines show truncation hints.
- **API**: `POST /companies/{company_id}/scrape` runs scrape + post-scrape pipeline for one registry company (background task + run_events / SSE like full runs).
- **Tests**: `test_cars24_custom_api`, `test_smartrecruiters`, `test_custom_scrape_debug`, expanded ATS detect coverage (~110+ phase1 tests).

## What it does

```
resume_summary + search_profile.yaml
  → scrape: Greenhouse · Lever · Ashby · Cutshort · Workday · SmartRecruiters · custom / custom_api
  → skip companies scraped within 24h (freshness cache)
  → dedup by URL (logged as dedup_done with job snapshot in run_events)
  → auto-discover new companies from scraped job URLs
  → filter: freshness (30d) · location · salary LPA · product-only · blocklist
  → role filter: drop DS/DevOps/mobile/PM titles
  → embed all filtered jobs → ChromaDB (nvidia/llama-nemotron-embed-vl-1b-v2:free)
  → semantic rank (embeddings) or TF-IDF fallback
  → top 50 → ONE LLM call → score 0–10 + skill gap
  → output/scored_jobs_TIMESTAMP.json
  → React app (Dashboard · Tracker · RunLogs · Companies · Settings)
```

**Cost per run: < $0.002 (~₹0.17)**

## Setup

```bash
git clone <repo>
cd role-miner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Edit search_profile.yaml to match your profile
```

Create `.env` (gitignored):
```
# LLM for scoring (OpenRouter recommended)
LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
SCORING_MODEL=deepseek/deepseek-chat-v3-0324:free

# Embeddings (same OpenRouter key works — model is free)
EMBED_API_KEY=sk-or-v1-...          # defaults to LLM_API_KEY if unset
EMBED_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free

# Company career URL discovery
DISCOVER_MODEL=tencent/hy3-preview:free
BRAVE_SEARCH_API_KEY=...            # optional — enables web search step

# Scraper freshness (skip companies scraped within this window)
SCRAPER_FRESHNESS_HOURS=24          # default 24h
```

## Usage

### CLI

```bash
# Seed company registry (run once)
python main.py bootstrap

# Run full pipeline
python main.py run
# → output/scored_jobs_20260501T143022Z.json

# Start API server
python main.py serve   # http://localhost:8000

# Clear scraper freshness so the next run re-scrapes every company
python main.py reset-scrape
```

Subcommands are explicit: `bootstrap | run | serve | reset-scrape` (no default).

### Full stack (API + React)

```bash
# Docker Compose: API on :8000, frontend on :3000
docker compose up

# Or dev mode
python main.py serve &
cd frontend && npm run dev   # proxies /api → :8000
```

## Configuration

Edit `search_profile.yaml`:

```yaml
skills: [React, TypeScript, Node.js, Python]
locations: [Bangalore, Hyderabad, Remote]
salary_min_lpa: 30
work_mode: [remote, hybrid]
company_type: [product]
exclude_companies: []
notice_days: 60
resume_summary: |
  Senior full-stack engineer, 8+ years, ...
```

## API

All routes are under the app root (e.g. `/jobs/latest`). The API uses a lightweight **user** row in SQLite: send **`X-User-Id: <id>`** to act as that user, or omit it / send `0` to use the default user created on first use.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs/latest` | Jobs across **all completed runs** for the **active search profile**, deduped by URL, **best score per URL**; query `min_score` (default **6**) |
| GET | `/jobs/run/{id}` | Jobs for one run (must belong to the user) |
| GET | `/jobs/tracked` | Jobs with any non-new tracker status |
| POST | `/jobs/status` | Set tracker status + notes (`url`, `status`, `notes`) — e.g. `saved`, `archived`, `applied`, `clicked` |
| POST | `/jobs/click` | Mark job as `clicked` when opening apply link (if still `new`) |
| GET | `/runs` | Run history (last 20) |
| GET | `/runs/{id}` | Run detail with all pipeline events |
| POST | `/trigger` | Start a new pipeline run, returns `run_id` |
| GET | `/stream/{run_id}` | SSE: live pipeline events (or replay from DB) |
| GET | `/stats` | Aggregate totals + per-source job counts |
| GET | `/companies` | All companies in registry |
| PATCH | `/companies/{id}` | Partial update: `careers_url` and/or `ats_type` (empty string clears; `ats_type` must be a known scraper or empty) |
| POST | `/companies/discover` | Discover career URLs for company names (SSE stream) |
| POST | `/companies/{id}/scrape` | Scrape one registry company and run filter → embed → rank → score (returns `run_id`) |
| GET | `/users` | List users |
| POST | `/users` | Create user |
| GET | `/me` | Current user (from `X-User-Id`) + active profile |
| GET | `/profile` | Active search profile (YAML-backed) |
| PUT | `/profile` | Update active profile |
| GET | `/profile/resume` | Resume metadata |
| POST | `/profile/resume` | Upload resume |
| GET | `/settings` | Runtime settings |
| PUT | `/settings` | Update runtime settings |

## Frontend views

**Dashboard** — job grid for the active profile: **min score** (default 6, API-aligned), work mode, company type, ESOP / notice filters, optional **hide archived / dismissed**. Cards: score badge, skill match vs gap, **Apply** (records **clicked** when first opened), **Save for later**, **Archive**, **Mark applied**. Detail drawer has full tracker dropdown + notes.

**Tracker** — grouped board for jobs you have marked (saved, archived, applied, clicked, etc.) with readable section titles.

**RunLogs** — per-run pipeline breakdown:
- Pipeline step tracker: Scrape → **Dedup** → Filter → Role → Embed → Rank → Score with live status badges
- Scraper table: all companies with per-company status (pending / scraping… / ✓ / ⏭ fresh / error)
- Company discovery: new companies found via ATS URL detection each run
- **Dedup**: unique job count after URL deduplication + expandable table of jobs in the log (capped)
- Filter drop chart: stale / location / salary / company_type / blocklist; **jobs passing rule filter** (table)
- Role filter: how many dropped + samples; **jobs passing role filter** (table)
- Embedding: jobs embedded count + model name
- Ranker: top similarity scores; **ranked jobs** table (similarity + links)
- Scorer: jobs scored · tokens · cost · score distribution chart · top 5 jobs · **all scored jobs table** · LLM prompt preview
- Errors panel: real-time error display with traceback (shown as soon as any error arrives)
- Live events terminal with timestamps via SSE; replays from DB for finished runs

**Companies** — registry browser with search + ATS filter. **Discover panel** (`+ Discover` button): paste company names, resolves career URLs via 4-step flow (cache → URL heuristics → Brave Search → LLM), streams results per-company, auto-adds to DB.

**Settings** — user switcher (`X-User-Id`), resume upload, profile editor tied to the pipeline.

## Company discovery flow

```
Company name
  → Step 1: DB cache (careers_url or ats_slug already known)
  → Step 2: URL heuristics (probe {name}.com/careers, /jobs, careers.{name}.com)
  → Step 3: Brave Search API (if BRAVE_SEARCH_API_KEY set)
  → Step 4: LLM batch (tencent/hy3-preview:free via OpenRouter)
  → save to registry + stream result to UI
```

## ChromaDB vector store

Two persistent collections (default path under `roleminer/registry/chroma/`):

| Collection | Populated | Use |
|---|---|---|
| `companies` | On bootstrap | Semantic company similarity search |
| `jobs` | Every run (all filter-passing jobs) | Cross-run semantic job search |

## Stack

- **Scraping**: HTTPX + tenacity retry; **Playwright** for custom career pages and ATS browser-detect fallback
- **ATS support**: Greenhouse · Lever · Ashby · Cutshort · Workday · **SmartRecruiters** · **custom** (Playwright) · **custom_api** (discovered JSON endpoints)
- **Storage**: SQLite (companies + runs + run_events) + ChromaDB (embeddings)
- **Pipeline**: rule filter → role filter → embed → semantic rank → single LLM score call
- **Embeddings**: `nvidia/llama-nemotron-embed-vl-1b-v2:free` via OpenRouter
- **LLM**: any OpenAI-compatible API via `LLM_API_KEY` + `LLM_BASE_URL`
- **API**: FastAPI + SSE (sse-starlette)
- **Frontend**: React 18 + Vite + TypeScript + Tailwind + React Query + Recharts

## Project structure

```
main.py                    # CLI: bootstrap | run | serve | reset-scrape
config.py                  # paths, env vars, model config
search_profile.yaml        # your job preferences
Dockerfile
docker-compose.yml
roleminer/
├── scrapers/              # greenhouse · lever · ashby · cutshort · workday · smartrecruiters · custom
├── registry/
│   ├── db.py              # SQLite CRUD (companies, runs, run_events, users, profiles, job_status)
│   ├── vector_store.py    # ChromaDB collections (companies + jobs)
│   ├── ats_detect.py      # ATS URL detection + embedded career links
│   ├── job_api_discover.py # scan JS bundles for proprietary job-list APIs
│   ├── browser_detect.py  # Playwright ATS detection fallback
│   ├── chroma/            # default Chroma persistence directory
│   └── career_finder.py   # 4-step company career URL discovery
├── pipeline/
│   ├── embedder.py        # OpenRouter embedding client
│   ├── ranker.py          # semantic rank (embeddings) or TF-IDF fallback
│   ├── filter.py
│   ├── role_filter.py
│   └── scorer.py
└── api/                   # FastAPI routes + SSE + auth header
    ├── auth.py            # X-User-Id → CurrentUser
    └── routes/            # jobs, users, preferences, companies, runs, stream, stats
frontend/
└── src/
    ├── views/             # Dashboard · Tracker · RunLogs · Companies · Settings
    ├── auth/              # user context for API client
    ├── components/        # JobCard · JobDetail · RunEventStream
    ├── lib/datetime.ts    # IST formatting helpers
    └── api/client.ts      # typed API client
tests/
└── phase1/                # 75 tests, all green
```

## Build phases

| Phase | Status | What |
|-------|--------|------|
| 1 | ✅ Done | Greenhouse · Lever · Ashby · Cutshort · SmartRecruiters + custom scrapers + filter + LLM scorer (110+ tests) |
| 2 | ✅ Done | Workday scraper · TF-IDF ranker · role filter · expanded seed companies |
| 3 | ✅ Done | Docker Compose · run_events DB · structured pipeline event logging |
| 4 | ✅ Done | FastAPI + SSE + React Dashboard + RunLogs with live stream |
| 5 | ✅ Done | ChromaDB embeddings · semantic ranker · company auto-discovery · career URL finder · RunLogs redesign |
| Remaining | Planned | Wellfound · YC · iimjobs · Naukri scrapers |

## Tests

```bash
pytest tests/phase1/ -v
# 110+ passed (includes live HTTP probes where safe)
```

Live HTTP tests hit real public APIs (Greenhouse/Lever/Ashby). LLM calls are mocked.

## Key constraints

- Salary always in LPA — never USD internally
- Never stores full JDs — company metadata only, JDs fetched fresh each run
- Service company filter is rule-based (fast), not LLM
- Single LLM call per run — batches top 50 jobs in 15-job chunks
- LLM provider agnostic: set `LLM_API_KEY` + `LLM_BASE_URL` for any OpenAI-compatible API
- Scraper freshness: companies scraped within `SCRAPER_FRESHNESS_HOURS` (default 24h) are skipped
- Stale "running" runs auto-cleaned to "failed" on server startup
- **Job shortlist** is per **active profile**: all completed runs for that profile are merged; each URL keeps its **best** score; dashboard defaults to **score ≥ 6**
