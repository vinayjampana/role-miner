# Module: api/

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app; lifespan (stale run cleanup on startup) |
| `auth.py` | `X-User-Id` header → `CurrentUser` (with `active_profile_id`) |
| `models.py` | Pydantic request/response models incl. `DiscoverRequest`/`DiscoverResult` |
| `dependencies.py` | Shared FastAPI deps |
| `routes/jobs.py` | `GET /jobs/latest|run|tracked`, `POST /jobs/status|click` |
| `routes/users.py` | `GET/POST /users`, `GET /me` |
| `routes/preferences.py` | Profile, resume upload, LLM settings |
| `routes/companies.py` | `GET /companies`, `POST /companies/discover` (SSE), `POST /companies/{id}/scrape` |
| `routes/runs.py` | Run management + trigger |
| `routes/stats.py` | Aggregate stats |
| `routes/stream.py` | SSE pipeline event stream |

## Auth

Header: `X-User-Id` (optional). Omit or `0` → default user via `ensure_default_user_id`.
`CurrentUser` carries `user_id` + `active_profile_id`.

## Key Endpoints

```
GET  /jobs/latest          → scored jobs for active profile (min_score=6 default)
GET  /jobs/run/{run_id}    → jobs from specific run
POST /jobs/status          → update tracker status
POST /jobs/click           → promote new → clicked

GET  /companies            → list companies
POST /companies/discover   → SSE stream; discover + add company
POST /companies/{id}/scrape → trigger single company scrape

GET  /stream/{run_id}      → SSE pipeline event stream
POST /runs/trigger         → start new pipeline run

GET  /me                   → current user + active profile
```

## SSE Pattern

`POST /companies/discover` and `GET /stream/{run_id}` both use SSE.
Events pushed as `data: {json}\n\n`.
Frontend uses `EventSource` or custom SSE client.

## Models (models.py highlights)

- `DiscoverRequest` — company name/url for discovery flow
- `DiscoverResult` — discovered careers URL + ATS type
- `JobStatus` — tracker status enum
- `RunEvent` — mirrors `run_events` table row
