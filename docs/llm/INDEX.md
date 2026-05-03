# SYSTEM SNAPSHOT

- India-first job discovery tool; scrapes Greenhouse + Workday (V1), scores vs candidate profile, surfaces ranked shortlist
- CLI (`main.py`) → scrape → fuzzy dedup → filter → embed → rank → LLM-score → FastAPI + React UI
- Key components: `scrapers/`, `registry/`, `pipeline/`, `api/`, `frontend/`
- Data store: SQLite (`db.py`) + ChromaDB (`vector_store.py`; persist dir via `CHROMA_PATH` env, see `config.py`)
- LLM: any OpenAI-compatible API; embeddings via OpenRouter
- Events: every pipeline step → `run_events` table → SSE stream → RunLogs UI
- Identity: JWT `Authorization: Bearer` (signed with `APP_SECRET`, default dev fallback in code); optional legacy `X-User-Id` only when `APP_SECRET` is unset/empty. Registration uses `REGISTRATION_TOKEN`. Per-user profiles + job tracker

## V1 SCOPE (ACTIVE)

- **Company registry**: static JSON file — `roleminer/registry/data/companies.json` (NOT the DB)
- **Active scrapers**: Greenhouse (HTTP JSON API) · Workday (HTTP CXS API); Playwright fallback if HTTP returns zero jobs
- **Disabled (code exists, not called)**: Lever · Ashby · Cutshort · SmartRecruiters · custom portal scraping · ATS auto-detection · career URL discovery · company auto-registration
- **Dedup**: URL-based + fuzzy title/company/location fingerprint (`dedup_fuzzy` in `scrapers/base.py`)
- **Scorer**: top **20** ranked jobs (was 50)

---

# TASK → DOC ROUTING

## Understand end-to-end execution flow
→ Read: /docs/llm/system-flow.md

## Add or modify a scraper
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/scrapers.md

## Add a company to scrape
→ **Registry (CLI / static)**: edit `roleminer/registry/data/companies.json`
→ Format: `{"company": "Name", "ats": "greenhouse|workday|…", "slug": "...", "careers_url": "..."}`
→ **API / UI**: `POST /api/companies` (auth required when JWT mode on). Allowed `ats_type` for create/patch: `greenhouse`, `lever`, `ashby`, `workday` (slug vs `careers_url` rules match ATS expectations)
→ Greenhouse / Lever / Ashby: `slug`; Workday: `careers_url` (CXS-style URL)

## Add or modify pipeline step (filter / rank / score)
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/pipeline.md

## Add or modify an API route
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/api.md

## Understand authentication (JWT, registration, legacy header)
→ Read: `roleminer/api/auth.py` (`get_current_user`), `roleminer/api/routes/auth.py` (`/auth/register`, `/auth/login`, `/auth/me`)
→ Env: `APP_SECRET`, `REGISTRATION_TOKEN`; users table may include `password_hash` (see `db.py` migrations)

## ChromaDB storage path
→ Env: `CHROMA_PATH` (optional override). Default under `roleminer/registry/chroma`. Used by `vector_store.get_client()`

## Debug a failed run or missing jobs
→ Read: /docs/llm/debugging.md

## Understand how jobs flow through the system (dedup / filter / rank / score)
→ Read: /docs/llm/data-flow.md

## Understand ATS detection / career URL discovery
→ Read: /docs/llm/modules/registry.md
→ NOTE: Both disabled in V1. Code in `ats_detect.py`, `career_finder.py`, `browser_detect.py`.

## Understand company discovery or auto-registration
→ Read: /docs/llm/modules/registry.md
→ NOTE: Disabled in V1. Static registry only (`registry/data/companies.json`).

## Understand embeddings / semantic ranking
→ Read: /docs/llm/modules/pipeline.md

## Understand frontend or UI components
→ Read: /docs/llm/modules/frontend.md

## Understand SSE event stream or run_events schema
→ Read: /docs/llm/system-flow.md

## Understand integrations (LLM / OpenRouter / Brave Search)
→ Read: /docs/llm/integrations.md

## Re-enable a disabled scraper (Lever / Ashby / Cutshort / SmartRecruiters)
→ Read: /docs/llm/extension-guide.md
→ Import the scraper in `main.py`; add ATS routing case in `_scrape_company()`

---

# LOADING RULES (CRITICAL)

- DO NOT load all docs
- ONLY open files relevant to current task
- If modifying code: ALWAYS read extension-guide.md first
- Prefer minimal context: INDEX → one doc → target file

---

# FILE MAP

| File | Purpose |
|---|---|
| `system-flow.md` | CLI → pipeline execution order; run_events schema |
| `data-flow.md` | Job object lifecycle: scrape → dedup → filter → rank → score → API |
| `extension-guide.md` | How to add/change scrapers, pipeline steps, routes |
| `debugging.md` | Failure points, stale runs, zero-job scenarios, SSE gaps |
| `integrations.md` | LLM, embedding, Brave Search config and call patterns |
| `modules/scrapers.md` | Per-ATS scraper logic; custom strategy order; `Job` dataclass |
| `modules/registry.md` | ATS detect, career_finder, browser_detect, vector_store, db CRUD |
| `modules/pipeline.md` | filter, role_filter, embedder, ranker, scorer internals |
| `modules/api.md` | FastAPI routes, JWT + legacy auth, models, SSE stream |
| `modules/frontend.md` | React views, API client, IST formatting, tracker UI |

---

# KEY FILES (V1)

| File | Role |
|---|---|
| `roleminer/registry/data/companies.json` | Static company registry — source of truth |
| `roleminer/registry/static_registry.py` | `load_companies()` — reads companies.json |
| `roleminer/scrapers/base.py` | `Job` dataclass · `dedup_by_url` · `dedup_fuzzy` |
| `roleminer/scrapers/greenhouse.py` | Greenhouse HTTP scraper (active) |
| `roleminer/scrapers/workday.py` | Workday HTTP scraper (active) |
| `roleminer/scrapers/custom.py` | Playwright scraper — Playwright fallback only in V1 |
| `roleminer/registry/db.py` | SQLite CRUD + users/password_hash + `get_freshness_by_name` + `set_freshness_by_name` |
| `roleminer/api/routes/auth.py` | `POST /auth/register`, `/auth/login`, `GET /auth/me` |
| `roleminer/api/auth.py` | JWT Bearer + legacy `X-User-Id` when `APP_SECRET` unset |
| `config.py` | `DB_PATH`, `CHROMA_PATH`, `COMPANIES_JSON_PATH`, env merge |
| `main.py` | Pipeline orchestration; `_scrape_company` routes greenhouse/workday |

---

# SELF-UPDATE RULE

If any doc seems outdated:
- Regenerate from codebase (`grep`, `Read`)
- Do NOT trust stale descriptions
- Source of truth: actual `.py` / `.tsx` files
