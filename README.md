# RoleMiner

Personal job discovery tool for senior engineering roles in India. Scrapes Greenhouse and Workday, scores against your profile, surfaces a ranked shortlist via CLI or React dashboard.

**Agent / LLM context** — task-oriented doc map: [docs/llm/INDEX.md](docs/llm/INDEX.md)

---

## Current State (V1)

**Active scrapers:** Greenhouse · Workday (HTTP-first, Playwright fallback on empty)

**Company registry:** static file at `roleminer/registry/data/companies.json` — edit this file to add or remove companies. No dynamic discovery in V1.

**Disabled (code kept, not called):**
- Lever / Ashby / Cutshort / SmartRecruiters scrapers
- Custom career portal scraping (Playwright-first path)
- ATS auto-detection from HTML/JS
- Career URL auto-discovery (4-step: cache → heuristics → Brave → LLM)
- Company auto-registration from scraped job URLs

**Pipeline:**
```
search_profile.yaml
  → load companies from registry/data/companies.json (Greenhouse + Workday only)
  → skip companies scraped within SCRAPER_FRESHNESS_HOURS (default 24h)
  → HTTP scrape → Playwright fallback if zero jobs
  → fuzzy dedup (URL + normalized title/company/location)
  → filter: age (30d) · location · salary LPA · company type · blocklist
  → role filter: drop DS / DevOps / mobile / PM titles
  → embed → ChromaDB (nvidia/llama-nemotron-embed-vl-1b-v2:free)
  → semantic rank (embeddings) or TF-IDF fallback
  → top 20 → ONE LLM call → score 0–10 + skill gap
  → output/scored_jobs_TIMESTAMP.json
  → React UI: Dashboard · Tracker · RunLogs · Companies · Settings
```

**Cost per run: < $0.002 (~₹0.17)**

---

## Setup

### 1. Clone and install

```bash
git clone <repo>
cd role-miner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` in the project root (gitignored):

```env
# LLM for scoring — any OpenAI-compatible API
LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
SCORING_MODEL=deepseek/deepseek-chat-v3-0324:free

# Embeddings (OpenRouter free model)
EMBED_API_KEY=sk-or-v1-...          # defaults to LLM_API_KEY if unset
EMBED_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free

# Scraper freshness — skip companies scraped within this window
SCRAPER_FRESHNESS_HOURS=24
```

`DISCOVER_MODEL` and `BRAVE_SEARCH_API_KEY` are unused in V1 but can be set for future use.

### 3. Edit your profile

Edit `search_profile.yaml`:

```yaml
skills: [Python, Go, TypeScript, Kubernetes]
locations: [Bangalore, Hyderabad, Remote]
salary_min_lpa: 30
work_mode: [remote, hybrid]
company_type: [product]
exclude_companies: []
notice_days: 60
resume_summary: |
  Senior backend engineer, 8+ years, distributed systems, ...
```

### 4. Add companies to scrape

Edit `roleminer/registry/data/companies.json`. Add any Greenhouse or Workday company:

```json
[
  {
    "company": "Razorpay",
    "ats": "greenhouse",
    "slug": "razorpaysoftwareprivatelimited",
    "careers_url": "https://boards.greenhouse.io/razorpaysoftwareprivatelimited"
  },
  {
    "company": "PayPal",
    "ats": "workday",
    "careers_url": "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs"
  }
]
```

**Greenhouse:** find the slug from `https://boards.greenhouse.io/{slug}` — the company's public job board URL.

**Workday:** use the `/wday/cxs/{tenant}/{board}/jobs` endpoint. Find it by opening DevTools on the company's Workday careers page and looking for POST requests to `myworkdayjobs.com`.

---

## Run

### CLI

```bash
# Embed companies into ChromaDB (run once after adding companies)
python main.py bootstrap

# Full pipeline: scrape → filter → rank → score
python main.py run
# Output: output/scored_jobs_20260501T143022Z.json

# Start API server (no scrape on start)
python main.py serve   # http://localhost:8000

# Force re-scrape all companies (clear freshness cache)
python main.py reset-scrape
```

### Full stack (API + React UI)

```bash
# Docker Compose — API on :8000, frontend on :3000
docker compose up

# Dev mode
python main.py serve &
cd frontend && npm run dev   # proxies /api → :8000
```

---

## Companies included (V1)

| Company | ATS | Notes |
|---|---|---|
| Razorpay | Greenhouse | slug: razorpaysoftwareprivatelimited |
| Groww | Greenhouse | slug: groww |
| Postman | Greenhouse | slug: postman |
| Slice | Greenhouse | slug: slice |
| PhonePe | Greenhouse | slug: phonepe |
| BrowserStack | Workday | wd3 tenant |
| PayPal | Workday | wd1 tenant |
| Adobe | Workday | wd5 tenant |
| Walmart Global Tech | Workday | wd5 tenant |

To add more: edit `roleminer/registry/data/companies.json`.

---

## API

Send `X-User-Id: <id>` header to act as a specific user, or omit it to use the default user (created on first `init_db`).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs/latest` | All completed runs for active profile, deduped by URL, best score per URL; `min_score` default 6 |
| GET | `/jobs/run/{id}` | Jobs for one run |
| GET | `/jobs/tracked` | Jobs with non-new tracker status |
| POST | `/jobs/status` | Set tracker status (`saved`, `applied`, `archived`, etc.) |
| POST | `/jobs/click` | Mark job clicked (promote `new` → `clicked`) |
| GET | `/runs` | Run history (last 20) |
| GET | `/runs/{id}` | Run detail + all pipeline events |
| POST | `/trigger` | Start new pipeline run, returns `run_id` |
| GET | `/stream/{run_id}` | SSE: live pipeline events |
| GET | `/stats` | Totals + per-source job counts |
| GET | `/companies` | Companies in registry |
| GET | `/me` | Current user + active profile |
| GET/PUT | `/profile` | Active search profile |
| POST | `/profile/resume` | Upload resume PDF |
| GET/PUT | `/settings` | Runtime settings |

---

## Frontend

**Dashboard** — job grid: score filter (default ≥ 6), work mode, company type, ESOP/notice filters. Cards: score badge, skill match/gap, Apply (logs click), Save, Archive, Mark Applied. Detail drawer with tracker dropdown + notes.

**Tracker** — board grouped by status (saved, applied, interviewing, etc.).

**RunLogs** — per-run pipeline breakdown: scraper table, dedup count, filter drop chart, role filter, embed, ranker scores, scorer results + cost. Live SSE during active runs.

**Companies** — registry browser. Edit `careers_url` and `ats_type` inline.

**Settings** — user switcher, resume upload, profile editor.

---

## Future roadmap

| Feature | Status |
|---|---|
| Lever + Ashby scrapers | Code exists, disabled — re-enable in `main.py` |
| Cutshort scraper | Code exists, disabled |
| SmartRecruiters scraper | Code exists, disabled |
| Custom career portal scraping (Playwright) | Code exists (`scrapers/custom.py`), disabled as primary path |
| ATS auto-detection from HTML | Code exists (`registry/ats_detect.py`), disabled |
| Career URL auto-discovery (4-step) | Code exists (`registry/career_finder.py`), disabled |
| Company auto-registration from job URLs | Code exists in pipeline, disabled |
| Wellfound / YC / iimjobs / Naukri | Not yet built |
| Dynamic scrape strategies (LLM-built JSON) | Code exists (`registry/strategy_builder.py`), disabled |
| Per-company scrape concurrency | Not yet built |

---

## Stack

- **Python 3.11+** · FastAPI · SQLite · ChromaDB · HTTPX · Playwright (fallback only)
- **React 18** · Vite · TypeScript · React Query · Recharts · Tailwind
- **Docker Compose** for local + VPS deploy
- **LLM**: any OpenAI-compatible API via `LLM_API_KEY` + `LLM_BASE_URL`
- **Embeddings**: `nvidia/llama-nemotron-embed-vl-1b-v2:free` via OpenRouter

---

## Project structure

```
main.py                          # CLI: bootstrap | run | serve | reset-scrape
config.py                        # env vars + paths
search_profile.yaml              # your job preferences
roleminer/
├── scrapers/
│   ├── greenhouse.py            # Greenhouse public JSON API
│   ├── workday.py               # Workday CXS JSON API
│   ├── base.py                  # Job dataclass · dedup_by_url · dedup_fuzzy
│   ├── custom.py                # Playwright custom portal (disabled as primary; used as fallback)
│   └── ...                      # lever, ashby, cutshort, smartrecruiters (disabled)
├── registry/
│   ├── data/
│   │   └── companies.json       # STATIC REGISTRY — edit this to add companies
│   ├── static_registry.py       # load_companies() — reads companies.json
│   ├── db.py                    # SQLite: runs, run_events, jobs, users, profiles, job_status
│   ├── vector_store.py          # ChromaDB collections (companies + jobs)
│   ├── ats_detect.py            # ATS URL detection (disabled in V1)
│   ├── browser_detect.py        # Playwright ATS detection (disabled in V1)
│   ├── career_finder.py         # 4-step career URL discovery (disabled in V1)
│   └── ...                      # job_api_discover, network_sniffer, strategy_builder (disabled)
├── pipeline/
│   ├── embedder.py              # OpenRouter embedding client
│   ├── ranker.py                # semantic rank or TF-IDF fallback
│   ├── filter.py                # rule-based filter
│   ├── role_filter.py           # title-based role filter
│   └── scorer.py                # single LLM call, top-20 jobs
└── api/
    ├── main.py                  # FastAPI app + startup cleanup
    ├── auth.py                  # X-User-Id → CurrentUser
    └── routes/                  # jobs · runs · stream · companies · users · preferences · stats
frontend/src/
├── views/                       # Dashboard · Tracker · RunLogs · Companies · Settings
├── components/                  # JobCard · JobDetail · RunEventStream
└── api/client.ts                # typed API client
```

---

## Key constraints

- Salary always in LPA — never USD internally
- Never stores full JDs — metadata only; JDs fetched fresh each run
- Service company filter is rule-based, not LLM
- Single LLM call per run — batches top **20** jobs
- LLM provider agnostic — set `LLM_API_KEY` + `LLM_BASE_URL`
- Scraper freshness: companies scraped within `SCRAPER_FRESHNESS_HOURS` (default 24h) are skipped
- Stale "running" runs auto-cleaned to "failed" on server startup
- Job shortlist is per active profile: all completed runs merged, best score per URL, default `min_score=6`

---

## Tests

```bash
pytest tests/phase1/ -v
# 110+ tests (live HTTP probes for Greenhouse/Lever/Ashby; LLM calls mocked)
```
