# System Flow

## CLI Entry Points (`main.py`)

```
bootstrap  → seed company registry → embed companies (ChromaDB)
run        → scrape → filter → embed → rank → score → persist
serve      → start FastAPI on :8000
reset-scrape → clear last_scraped_at
```

## Pipeline Execution Order (`run`)

```
1. scrape_start event emitted
2. For each company (skip if within SCRAPER_FRESHNESS_HOURS):
   - scraper_start → run ATS-specific scraper → scraper_done / scraper_skipped
3. discover_done  → auto-register new companies from job URLs
4. dedup_done     → deduplicate by job_url
5. filter_done    → rule-based filter (location, salary, service co)
6. role_filter_done → role keyword filter
7. embed_done     → ChromaDB upsert
8. rank_done      → semantic rank (or TF-IDF fallback)
9. score_done     → single LLM call, top 50 jobs, structured JSON
```

## run_events Table Schema

| column | type | notes |
|---|---|---|
| id | int PK | |
| run_id | text | uuid |
| event_type | text | see event types below |
| data | text | JSON blob |
| created_at | text | ISO timestamp |

## Event Types & Key Data Fields

| event_type | key data |
|---|---|
| `scrape_start` | `total_sources`, `companies[]`, `freshness_hours` |
| `scraper_start` | `company`, `ats` |
| `scraper_done` | `jobs_fetched`, `duration_ms`, `error` |
| `scraper_skipped` | `last_scraped_hours_ago`, `freshness_hours` |
| `discover_done` | `new_companies`, `names[]` |
| `dedup_done` | `total_in`, `total_out`, `removed`, `jobs{total,items[]}` |
| `filter_done` | `total_in/out`, `dropped_*`, `sample_dropped[]`, `jobs_passed` |
| `role_filter_done` | `total_in/out`, `dropped`, `sample_dropped[]`, `jobs_passed` |
| `embed_done` | `jobs_embedded`, `model` |
| `rank_done` | `total_ranked`, `top_scores[]`, `sent_to_scorer`, `jobs_ranked` |
| `score_done` | `jobs_scored`, `tokens_used`, `cost_usd`, `jobs_scored_detail` |
| `error` | `step`, `company`, `error`, `traceback` |

## SSE Stream

`GET /stream/{run_id}` — polls `run_events` table, pushes as SSE.
Frontend `RunEventStream` component consumes it.
