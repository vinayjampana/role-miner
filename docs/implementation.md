# RoleMiner — 4-Phase Build + Test Plan

Each phase ends with a working, tested checkpoint. Build phase → write tests → pass → commit → start next phase.

---

## Phase 1 — Core Pipeline (end-to-end working)

**Goal:** `python main.py run` scrapes 4 sources, filters, scores, writes `output/scored_jobs_TIMESTAMP.json`.

### Build

| File | What |
|------|------|
| `search_profile.yaml` | Schema: skills, locations, salary_min_lpa, work_mode, company_type, exclude_companies, notice_days |
| `config.py` | Paths, model names, API keys from env |
| `roleminer/registry/db.py` | SQLite CRUD — companies table + runs table |
| `roleminer/scrapers/base.py` | `Job` dataclass · `ProxySession` · retry decorator · rate limiter · `dedup_by_url()` |
| `roleminer/scrapers/greenhouse.py` | `GET /v1/boards/{slug}/jobs?content=true` → `list[Job]` |
| `roleminer/scrapers/lever.py` | `GET /v0/postings/{slug}?mode=json` → `list[Job]` |
| `roleminer/scrapers/ashby.py` | `POST /posting-api/job-board/{slug}` → `list[Job]` |
| `roleminer/scrapers/cutshort.py` | `GET /api/public/jobs` with skills+location params → `list[Job]` |
| `roleminer/pipeline/classifier.py` | Rule-based product/service classifier, LLM fallback for ambiguous |
| `roleminer/pipeline/filter.py` | Date · location · salary · company_type · blocklist · notice period regex · ESOP regex |
| `roleminer/pipeline/scorer.py` | LLM batch score top 50 → structured JSON, parse to `ScoredJob` |
| `main.py` | `bootstrap` and `run` commands |

### Test (`tests/phase1/`)

| Test | What to verify |
|------|---------------|
| `test_job_dataclass.py` | `Job` fields present, types correct, optional fields default safely |
| `test_greenhouse.py` | Live call to a known public slug (e.g. `lever`) → returns `list[Job]`, all have URL + title + date |
| `test_lever.py` | Live call → same shape checks |
| `test_ashby.py` | Live call → same shape checks |
| `test_cutshort.py` | Live call with `skills=React&location=Bangalore` → at least 1 result |
| `test_dedup.py` | Feed 10 jobs with 3 duplicate URLs → output has 7 |
| `test_classifier.py` | "TCS" → `service`; "Sarvam AI" → `product`; ambiguous triggers LLM mock |
| `test_filter.py` | Jobs outside salary floor filtered out; stale jobs (>7d) filtered; blocklist applied |
| `test_filter_notice.py` | "immediate joiner" in JD text → `notice_compatible=False` when notice_days > 0 |
| `test_filter_esop.py` | "ESOP" / "equity" / "stock options" in JD → `has_esop=True` |
| `test_scorer.py` | Mock LLM response → `ScoredJob` list parsed correctly, score in 0–10 |
| `test_db.py` | Insert company → fetch → update `last_scraped_at` → delete |
| `test_end_to_end.py` | Full `main.py run` with 2 real slugs → `output/*.json` exists, contains scored jobs |

**Pass criteria:** all tests green, `main.py run` produces valid JSON with ≥1 scored job.

---

## Phase 2 — Broader Scraping + Embeddings

**Goal:** 3 more scrapers live, ChromaDB semantic search working, TF-IDF pre-rank in pipeline.

### Build

| File | What |
|------|------|
| `roleminer/scrapers/wellfound.py` | GraphQL with `locationSlug: "india"` — India filter mandatory |
| `roleminer/scrapers/yc.py` | HTTP scrape YC job board, parse HTML → `list[Job]` |
| `roleminer/scrapers/iimjobs.py` | HTTP scrape iimjobs listings → `list[Job]` |
| `roleminer/scrapers/workday.py` | Unofficial JSON API per company, tenant ID stored in registry |
| `roleminer/registry/embedder.py` | ChromaDB: embed company profiles, semantic search returning top-N slugs |
| `roleminer/pipeline/ranker.py` | TF-IDF over job title + description vs profile skills → rank score |
| `main.py bootstrap` | Embed all companies after seeding registry |
| SQLite `runs` table | Store per-run metadata: timestamp, jobs_found, tokens_used, cost_usd |

### Test (`tests/phase2/`)

| Test | What to verify |
|------|---------------|
| `test_wellfound.py` | Response has India jobs (location field contains Indian city or "Remote") |
| `test_yc.py` | Parses ≥1 job, has URL and title |
| `test_iimjobs.py` | Parses ≥1 job, salary in LPA |
| `test_workday.py` | Mock HTTP → tenant ID extracted + stored, jobs parsed correctly |
| `test_embedder.py` | Embed 5 fake company profiles → semantic query "Bangalore Series B product company" returns correct top-3 |
| `test_ranker.py` | Job with 4/5 profile skills ranks above job with 1/5 skills |
| `test_run_history.py` | After `main.py run`, `runs` table has 1 row with non-null timestamp and job count |
| `test_full_pipeline.py` | All 7 scrapers run (mocked for wellfound/yc/iimjobs), dedup + filter + rank + score works end-to-end |

**Pass criteria:** `python main.py bootstrap` embeds companies; `python main.py run` uses ChromaDB to select companies, TF-IDF narrows to 50 before LLM call.

---

## Phase 3 — Naukri + Infrastructure

**Goal:** Naukri email parse working, Docker Compose runs full stack on Hetzner.

### Build

| File | What |
|------|------|
| `roleminer/scrapers/naukri.py` | Option B: IMAP/Gmail → parse Naukri alert emails → extract job URLs + metadata |
| `roleminer/scrapers/naukri_browser.py` | Option A: Playwright + stealth + Smartproxy (fallback only) |
| `docker-compose.yml` | Services: `scraper` · `api` · `frontend` · `chromadb` |
| `Dockerfile` | Python service: scraper + FastAPI in one container |
| `.env.example` | All required env vars documented |
| Smartproxy integration | Proxy URL injected via `PROXY_URL` env var into `ProxySession` |

### Test (`tests/phase3/`)

| Test | What to verify |
|------|---------------|
| `test_naukri_email_parse.py` | Feed sample Naukri alert email HTML → parses title, company, URL, location correctly |
| `test_naukri_dedup.py` | Same job URL from Naukri + Greenhouse → deduped to 1 |
| `test_docker_compose.py` | `docker compose up --build -d` → all services healthy within 30s |
| `test_proxy_session.py` | `ProxySession` with mock proxy URL → requests route through proxy headers |

**Pass criteria:** `docker compose up` starts all services; Naukri email parse returns valid jobs from fixture email.

---

## Phase 4 — API + Frontend

**Goal:** React dashboard live at `localhost:5173`, SSE stream works, job cards render with score + skill gap.

### Build

**Backend (`roleminer/api/`)**

| File | What |
|------|------|
| `api/main.py` | FastAPI app, CORS, lifespan |
| `api/routes/jobs.py` | `GET /jobs/latest` · `GET /jobs/history` |
| `api/routes/stream.py` | `GET /stream` — SSE, one event per scraper source as jobs arrive |
| `api/routes/search.py` | `POST /search` — natural language → ChromaDB → matched companies |
| `api/routes/stats.py` | `GET /stats` — token cost, run count, source hit rate |
| `api/models.py` | Pydantic response models for all endpoints |

**Frontend (`frontend/src/`)**

| Component | What |
|-----------|------|
| `JobCard` | Score badge (color: green ≥7, yellow 5–6, red <5) · company · title · location · salary LPA · ESOP tag |
| `SkillGap` | "have" chips (green) + "gap" chips (red) |
| `Dashboard` | Ranked job list · filter sidebar (location, work_mode, score, company_type) |
| `LiveProgress` | SSE stream → each source lights up as data arrives |
| `JobDetail` | Drawer: full JD · skill radar (Recharts) · apply button |
| `CompareView` | Side-by-side 2–3 jobs: score · salary · stack · notice compat |
| `ClusterView` | UMAP 2D scatter — jobs grouped by domain/seniority (compute UMAP server-side) |
| `TrendChart` | Weekly skill demand over time (Recharts line chart) |
| `CostDashboard` | Per-run token breakdown + spend history |
| `SearchBar` | Natural language → POST /search → highlight matched companies |

### Test (`tests/phase4/`)

| Test | What to verify |
|------|---------------|
| `test_jobs_endpoint.py` | `GET /jobs/latest` → 200, valid `ScoredJob` list |
| `test_stream_endpoint.py` | `GET /stream` → SSE events, each has `source` and `count` fields |
| `test_search_endpoint.py` | `POST /search {"query": "Bangalore Series B fintech"}` → returns matched companies |
| `test_stats_endpoint.py` | `GET /stats` → has `total_runs`, `total_cost_usd`, `sources` |
| `test_pydantic_models.py` | All response models serialize/deserialize correctly |

**Frontend smoke tests (manual + Playwright):**
- Dashboard renders job cards with score badge
- Filter by "remote" → only remote jobs shown
- Click job card → detail drawer opens
- Live progress: start `main.py run` → SSE stream shows sources lighting up
- Compare: select 2 jobs → compare view renders both columns

**Pass criteria:** `docker compose up` → `localhost:5173` loads dashboard with scored jobs; SSE stream live-updates during a run.

---

## Commit Cadence

```
feat(phase1): core pipeline — scrapers + filter + scorer
feat(phase1): tests passing — greenhouse, lever, ashby, cutshort, filter, scorer
feat(phase2): wellfound + yc + iimjobs + workday scrapers
feat(phase2): chromadb embedder + tfidf ranker + run history
feat(phase3): naukri email parse + docker compose
feat(phase4): fastapi routes — jobs, stream, search, stats
feat(phase4): react dashboard — job cards, filters, live stream, job detail
```

---

## Done Definition

- All phase tests green (`pytest tests/ -v`)
- `docker compose up` → full stack runs
- `main.py run` costs < $0.002
- Dashboard shows ranked jobs with score, skill gap, salary LPA, ESOP tag
