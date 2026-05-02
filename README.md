# RoleMiner

Personal job discovery tool for senior engineering roles in India. Scrapes 9 sources, scores against your profile, surfaces a ranked shortlist.

## What it does

```
resume.pdf + search_profile.yaml
  → scrape 9 sources (Greenhouse, Lever, Ashby, Cutshort, Wellfound, YC, iimjobs, Workday, Naukri)
  → dedup by URL
  → filter: freshness · location · salary LPA · product-only · blocklist
  → keyword pre-rank (TF-IDF)
  → top 50 → ONE LLM call → score 0–10 + skill gap
  → output/scored_jobs_TIMESTAMP.json
  → React dashboard
```

**Cost per run: < $0.002 (~₹0.17)**

## Setup

```bash
git clone <repo>
cd role-miner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp search_profile.yaml.example search_profile.yaml   # edit to match your profile
# drop resume.pdf in project root

export OPENAI_API_KEY=sk-...   # or DEEPSEEK_API_KEY + SCORING_MODEL=deepseek-...
```

## Usage

```bash
# Seed company registry (run once)
python main.py bootstrap

# Run full pipeline
python main.py run
# → output/scored_jobs_20260501_143022.json
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

## Stack

- **Scraping**: HTTPX + Playwright (Naukri only)
- **Storage**: SQLite (company registry + run history) · ChromaDB (embeddings, Phase 2)
- **Pipeline**: rule-based filter → TF-IDF rank → single LLM score call
- **API**: FastAPI (Phase 4)
- **Frontend**: React 18 + Vite + TypeScript (Phase 4)

## Project structure

```
main.py                    # CLI: bootstrap | run | serve
config.py                  # paths, env vars, model config
search_profile.yaml        # your job preferences
roleminer/
├── scrapers/              # one file per source, all return Job dataclass
├── registry/              # SQLite CRUD
└── pipeline/              # filter → rank → score
tests/
└── phase1/                # 75 tests, all green
```

## Build phases

| Phase | Status | What |
|-------|--------|------|
| 1 | ✅ Done | Greenhouse · Lever · Ashby · Cutshort + filter + scorer |
| 2 | Planned | Wellfound · YC · iimjobs · Workday + ChromaDB + TF-IDF |
| 3 | Planned | Naukri email parse + Docker Compose + VPS deploy |
| 4 | Planned | FastAPI + React dashboard |

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
- Single LLM call per run — batches top 50 jobs
- Wellfound always uses India location filter
