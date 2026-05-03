# Data Flow

## Job Object Lifecycle

```
Scraper → Job dataclass → dedup → filter → role_filter → embed → rank → LLM score → DB persist → API → Frontend
```

## Job Dataclass (all scrapers return same shape)

```python
@dataclass
class Job:
    title: str
    company: str
    url: str          # dedup key
    location: str
    salary_lpa: float | None   # ALWAYS LPA, never USD
    description: str | None    # NOT stored — fetched fresh each run
    ats: str
    source_company_id: int
```

## Dedup Logic

- Key: `job_url` (normalized)
- Same URL from multiple sources → keep first seen
- Post-dedup: `dedup_done` event with snapshot

## Filter Chain

1. **filter.py** — location (India), salary range, service company (rule-based, not LLM)
2. **role_filter.py** — `_looks_like_job_title`: whole-word regex, max 10 words, marketing guards

## Ranking

- If `EMBED_API_KEY` set: semantic cosine similarity via ChromaDB
- Fallback: TF-IDF (`sklearn`)
- Output: jobs sorted by `rank_score`, top N sent to scorer

## LLM Scoring

- Single call per run
- Batch top 50 jobs
- Structured JSON output: `{job_url, score, reason}`
- Score range: 0–10; `GET /jobs/latest` default `min_score=6`

## Job Shortlist Query (`GET /jobs/latest`)

- All **completed** runs for user's **active** `search_profile_id`
- Dedup by `job_url`
- Keep `max(score)` per URL (tie-break: latest run)
- Filter by `min_score` (default 6)

## Tracker States

`new` → `clicked` → `saved` → `applied` → `interviewing` → `rejected` / `dismissed` / `archived`

`POST /jobs/click` promotes `new` → `clicked` automatically.
