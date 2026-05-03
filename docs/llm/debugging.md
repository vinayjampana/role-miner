# Debugging

## Common Failure Points

### Zero jobs from a company

1. Check `run_events` for `scraper_done` — `jobs_fetched=0`
2. If custom scraper: check `validate_custom_scrape()` rejection — marketing/nav garbage detected
3. Zero-job fallback fires `find_redirect_via_cta` → updates `careers_url` in DB → retry next run
4. Check `browser_detect` log — may have detected new ATS portal (Signal 5)

### Jobs scraped but not in shortlist

1. Check `dedup_done` — URL collision with prior run?
2. Check `filter_done` — dropped by location/salary/service-co filter?
3. Check `role_filter_done` — title failed `_looks_like_job_title`?
4. Check `rank_done` — ranked too low, not in top 50 sent to scorer?
5. Check `score_done` — scored < `min_score` (default 6)?
6. Check `GET /jobs/latest` — active `search_profile_id` mismatch?

### Run stuck in `running` state

- Server restart auto-clears via `cleanup_stale_runs()` in lifespan
- Manual: `UPDATE runs SET status='failed' WHERE status='running'` in SQLite

### SSE stream silent / no events

1. Confirm run_id exists in `runs` table
2. Check `run_events` table for rows with that run_id
3. Check `GET /stream/{run_id}` — returns 404 if run not found

### LLM scoring fails

1. Check `SCORING_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` env vars
2. Check `score_done` or `error` event for traceback
3. Structured JSON parse failure → check model output format

### Embedding fails / TF-IDF fallback active

- `EMBED_API_KEY` missing or invalid → falls back to TF-IDF silently
- Check `embed_done` event `model` field — confirms which was used

### Company not being scraped

- Check `last_scraped_at` vs `SCRAPER_FRESHNESS_HOURS` (default 24h)
- `scraper_skipped` event confirms skip with `last_scraped_hours_ago`
- Force rescrape: `python main.py reset-scrape`

## Useful Queries

```sql
-- Last run events
SELECT event_type, data, created_at FROM run_events
WHERE run_id = '<run_id>' ORDER BY id;

-- Stuck runs
SELECT * FROM runs WHERE status = 'running';

-- Jobs for profile
SELECT job_url, score FROM jobs
WHERE profile_id = <id> ORDER BY score DESC LIMIT 20;
```

## Log Patterns

Server logs `[pipeline] run_id=…` summary per step.
Each step includes timing + job counts.
