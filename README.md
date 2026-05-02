# RoleMiner

Personal job discovery tool for senior engineering roles in India. Scrapes multiple sources, scores against your profile, surfaces a ranked shortlist via CLI or React dashboard.

## What it does

```
resume_summary + search_profile.yaml
  → scrape: Greenhouse · Lever · Ashby · Cutshort · Workday
  → dedup by URL
  → filter: freshness (30d) · location · salary LPA · product-only · blocklist
  → role filter: drop DS/DevOps/mobile/PM titles
  → TF-IDF pre-rank (scikit-learn cosine similarity)
  → top 50 → ONE LLM call → score 0–10 + skill gap
  → output/scored_jobs_TIMESTAMP.json
  → React dashboard (Dashboard + RunLogs with live SSE)
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
LLM_API_KEY=sk-...
LLM_BASE_URL=https://opencode.ai/zen/v1   # or leave empty for OpenAI
SCORING_MODEL=deepseek-v4-flash           # or gpt-4o-mini etc.
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
```

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

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs/latest` | Jobs from most recent run |
| GET | `/jobs/run/{id}` | Jobs for a specific run |
| GET | `/runs` | Run history (last 20) |
| GET | `/runs/{id}` | Run detail with all pipeline events |
| POST | `/trigger` | Start a new pipeline run, returns `run_id` |
| GET | `/stream/{run_id}` | SSE: live pipeline events (or replay from DB) |
| GET | `/stats` | Aggregate totals + per-source job counts |

## Frontend views

**Dashboard** — job grid with filters: min score slider, work mode, company type, ESOP-only, notice-compatible-only. Each card shows score badge, skill matches (green) vs gaps (red), apply link.

**RunLogs** — per-run pipeline breakdown:
- Scraper table: company · ATS · jobs fetched · duration ms · error
- Filter drop chart: stale / location / salary / company_type / blocklist
- Role filter: how many dropped + sample titles
- TF-IDF scores: top 10 cosine similarity values
- Scorer: jobs scored · tokens · cost · score distribution chart · top 5 jobs · LLM prompt preview
- Live events via SSE while run is active; replays from DB for finished runs

## Stack

- **Scraping**: HTTPX + tenacity retry
- **ATS support**: Greenhouse · Lever · Ashby · Cutshort · Workday
- **Storage**: SQLite (companies + runs + run_events)
- **Pipeline**: rule filter → role filter → TF-IDF rank → single LLM score call
- **LLM**: any OpenAI-compatible API via `LLM_API_KEY` + `LLM_BASE_URL`
- **API**: FastAPI + SSE (sse-starlette)
- **Frontend**: React 18 + Vite + TypeScript + Tailwind + React Query + Recharts

## Project structure

```
main.py                    # CLI: bootstrap | run | serve
config.py                  # paths, env vars, model config
search_profile.yaml        # your job preferences
Dockerfile
docker-compose.yml
roleminer/
├── scrapers/              # greenhouse · lever · ashby · cutshort · workday
├── registry/              # db.py: SQLite CRUD (companies, runs, run_events)
├── pipeline/              # filter → role_filter → ranker → scorer
└── api/                   # FastAPI routes + SSE stream
frontend/
└── src/
    ├── views/             # Dashboard · RunLogs
    ├── components/        # JobCard · JobDetail · RunEventStream
    └── api/client.ts      # typed API client
tests/
└── phase1/                # 75 tests, all green
```

## Build phases

| Phase | Status | What |
|-------|--------|------|
| 1 | ✅ Done | Greenhouse · Lever · Ashby · Cutshort + filter + LLM scorer (75 tests) |
| 2 | ✅ Done | Workday scraper · TF-IDF ranker · role filter · expanded seed companies |
| 3 | ✅ Done | Docker Compose · run_events DB · structured pipeline event logging |
| 4 | ✅ Done | FastAPI + SSE + React Dashboard + RunLogs with live stream |
| Remaining | Planned | Wellfound · YC · iimjobs · Naukri scrapers · ChromaDB embeddings |

## Tests

```bash
pytest tests/phase1/ -v
# 75 passed
```

Live HTTP tests hit real public APIs (Greenhouse/Lever/Ashby). LLM calls are mocked.

## Key constraints

- Salary always in LPA — never USD internally
- Never stores full JDs — company metadata only, JDs fetched fresh each run
- Service company filter is rule-based (fast), not LLM
- Single LLM call per run — batches top 50 jobs in 15-job chunks
- LLM provider agnostic: set `LLM_API_KEY` + `LLM_BASE_URL` for any OpenAI-compatible API
