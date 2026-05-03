# Extension Guide

## Add a New Scraper

1. Create `roleminer/scrapers/<ats_name>.py`
2. Implement function returning `list[Job]` — same `Job` dataclass as all others
3. Register in `roleminer/scrapers/__init__.py` dispatch map
4. Add ATS name to `ats_detect.py` patterns if detectable from HTML

**Key constraint**: never store full JD text. Return metadata only.

## Add a New ATS Detection Pattern

- File: `roleminer/registry/ats_detect.py`
- Add URL pattern to relevant regex or dict
- For unsupported ATS portals: add to `_JOB_PORTAL_RE` in `browser_detect.py` (Signal 5)

## Modify Custom Scraper Strategy

File: `roleminer/scrapers/custom.py`

Strategy order (DO NOT change without understanding fallback chain):
```
0. XHR network intercept (SPA/React)
1. Embedded JSON (__NEXT_DATA__)
2. Job card DOM selectors
3. Link heuristics
→ zero-job fallback: find_redirect_via_cta → update careers_url in DB
```

After Playwright scrape: `validate_custom_scrape()` called (≤80 tokens, `DISCOVER_MODEL`) to reject nav/marketing garbage.

## Add a Pipeline Step

1. Create `roleminer/pipeline/<step>.py`
2. Input: `list[Job]`, output: `list[Job]` (or augmented)
3. Emit event via `emit_event(run_id, "step_done", {...})` in `registry/db.py`
4. Wire into `main.py` run sequence
5. Add event type to `system-flow.md`

## Add an API Route

1. Create `roleminer/api/routes/<feature>.py`
2. Register router in `roleminer/api/main.py`
3. Add Pydantic models to `roleminer/api/models.py`
4. Use `CurrentUser` from `auth.py` for user identity
5. Add typed method to `frontend/src/api/client.ts`

## Modify Job Scoring

File: `roleminer/pipeline/scorer.py`
- Single LLM call pattern — do not add per-job calls (cost budget: <$0.002/run)
- Batch size: top 50
- Model: `SCORING_MODEL` env var

## Modify `_looks_like_job_title`

File: `roleminer/scrapers/custom.py` (or `role_filter.py`)
- Uses `_JOB_KEYWORD_RE` (whole-word regex)
- Max 10 words
- Guards: `_MARKETING_RE` + `_CONTENT_SUFFIX_RE`
- Ambiguous single words (product/data/sales) require qualifying role word
- No substring matching

## Config Changes

All env vars in `config.py`. Never hardcode provider, model, or API keys.
