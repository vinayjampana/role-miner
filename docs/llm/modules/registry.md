# Module: registry/

## Files

| File | Purpose |
|---|---|
| `db.py` | SQLite CRUD: companies, runs, run_events, jobs, users, profiles; `cleanup_stale_runs`; `get_jobs_for_profile` |
| `vector_store.py` | ChromaDB: companies + jobs collections; upsert + query |
| `ats_detect.py` | Detect ATS from HTML/URL; extract embedded careers URLs; SmartRecruiters detect |
| `career_finder.py` | 4-step career URL discovery: cache → heuristic → Brave Search → LLM |
| `browser_detect.py` | Playwright ATS fallback: network intercept + DOM + href scan (Signal 5) |
| `job_api_discover.py` | Proprietary job JSON API discovery from JS chunks + careers.* subdomain fallback |
| `discovery_agent.py` | Company auto-discovery orchestration |
| `network_sniffer.py` | XHR/fetch intercept for SPA job APIs |
| `strategy_builder.py` | Selects scrape strategy per company |

## db.py Key Functions

- `get_jobs_for_profile(user_id, profile_id)` — dedup by URL, max(score) per URL
- `cleanup_stale_runs()` — called on server startup; marks stuck `running` → `failed`
- `emit_event(run_id, event_type, data)` — writes to `run_events`, queues SSE
- `ensure_default_user_id(header)` — `X-User-Id` → user id

## career_finder.py 4-Step Flow

```
1. Cache lookup (DB careers_url)
2. Heuristic (common paths: /careers, /jobs, /about/careers)
3. Brave Search (BRAVE_SEARCH_API_KEY required)
4. LLM fallback (DISCOVER_MODEL)
```

## ATS Detection Priority

1. `ats_detect.py` — URL pattern match (fast, no network)
2. `ats_detect.py` — embedded HTML scan (greenhouse/lever/ashby iframes)
3. `browser_detect.py` — Playwright fallback (network + DOM + Signal 5 href scan)

## Company Auto-Discovery

After each scrape run: job URLs parsed for ATS patterns → new companies inserted automatically → `discover_done` event.
