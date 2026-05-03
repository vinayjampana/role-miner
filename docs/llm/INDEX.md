# SYSTEM SNAPSHOT

- India-first job discovery tool; scrapes ATS sources, scores vs candidate profile, surfaces ranked shortlist
- CLI (`main.py`) → scrape → filter → embed → rank → LLM-score → FastAPI + React UI
- Key components: `scrapers/`, `registry/`, `pipeline/`, `api/`, `frontend/`
- Data store: SQLite (`db.py`) + ChromaDB (`vector_store.py`)
- LLM: any OpenAI-compatible API; embeddings via OpenRouter
- Events: every pipeline step → `run_events` table → SSE stream → RunLogs UI
- Identity: optional `X-User-Id` header; per-user profiles + job tracker

---

# TASK → DOC ROUTING

## Understand end-to-end execution flow
→ Read: /docs/llm/system-flow.md

## Add or modify a scraper
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/scrapers.md

## Add or modify pipeline step (filter / rank / score)
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/pipeline.md

## Add or modify an API route
→ Read: /docs/llm/extension-guide.md
→ Then: /docs/llm/modules/api.md

## Debug a failed run or missing jobs
→ Read: /docs/llm/debugging.md

## Understand how jobs flow through the system (dedup / filter / rank / score)
→ Read: /docs/llm/data-flow.md

## Understand ATS detection / career URL discovery
→ Read: /docs/llm/modules/registry.md

## Understand company discovery or auto-registration
→ Read: /docs/llm/modules/registry.md

## Understand embeddings / semantic ranking
→ Read: /docs/llm/modules/pipeline.md

## Understand frontend or UI components
→ Read: /docs/llm/modules/frontend.md

## Understand SSE event stream or run_events schema
→ Read: /docs/llm/system-flow.md

## Understand integrations (LLM / OpenRouter / Brave Search)
→ Read: /docs/llm/integrations.md

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
| `modules/api.md` | FastAPI routes, auth, models, SSE stream |
| `modules/frontend.md` | React views, API client, IST formatting, tracker UI |

---

# SELF-UPDATE RULE

If any doc seems outdated:
- Regenerate from codebase (`grep`, `Read`)
- Do NOT trust stale descriptions
- Source of truth: actual `.py` / `.tsx` files
