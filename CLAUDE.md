# RoleMiner — CLAUDE.md

India-first job discovery tool. Scrapes 9 sources, scores against candidate profile, surfaces ranked shortlist via FastAPI + React.

## Project Goal

Personal tool for Vinay to find relevant senior engineering roles in India. Not a SaaS product — optimize for correctness and cost, not scale.

## Stack

- Python 3.11+ · FastAPI · SQLite · ChromaDB · HTTPX · Playwright
- React 18 · Vite · TypeScript · Zustand · React Query · Recharts
- Docker Compose (local + VPS deploy)
- LLM: DeepSeek or GPT-4o-mini (scoring only) · text-embedding-3-small (embeddings)

## Key Constraints

- **India salary always LPA** — never USD internally
- **Never store full JDs** — company metadata only, fresh JDs fetched each run
- **Dedup by URL** before scoring — same job appears on multiple sources
- **Wellfound MUST use India location filter** — without it skews US-heavy
- **Naukri**: email parse first, browser scrape fallback only if coverage insufficient
- **Service company filter is rule-based**, not LLM
- **Single LLM call per run** — batch score top 50 jobs, structured JSON output
- All scrapers return same `Job` dataclass — decoupled from pipeline

## Directory Layout

```
roleminer/
├── main.py                  # CLI: bootstrap | run | serve
├── config.py                # model config, proxy, paths
├── search_profile.yaml      # user-edited job preferences
├── resume.pdf               # user drops here
├── registry/                # SQLite + ChromaDB
├── scrapers/                # one file per source
├── pipeline/                # filter → rank → score
├── api/                     # FastAPI
└── frontend/                # React + Vite
```

## Running Locally

```bash
# Phase 1 (core pipeline)
python main.py bootstrap    # seed company registry
python main.py run          # scrape → filter → score → output JSON

# Phase 4 (with API + frontend)
docker compose up
```

## Testing Convention

- Each phase has a `tests/phaseN/` directory
- Use `pytest` with real HTTP calls where safe (Greenhouse, Lever APIs are public)
- Mock only: Playwright, external LLM calls, proxy sessions
- Run with: `pytest tests/phaseN/ -v`

## Cost Budget

- < $0.002 per run (< ₹0.17)
- Bootstrap (one-time): < $0.001

## Detailed Plan

See `docs/plan.md` for full implementation plan, scraper strategies, data schema, and API design.
