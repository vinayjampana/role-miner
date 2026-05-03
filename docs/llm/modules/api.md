# Module: api/

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app; lifespan (stale run cleanup on startup) |
| `auth.py` | JWT `Authorization: Bearer` → `CurrentUser`; legacy `X-User-Id` when `APP_SECRET` unset |
| `routes/auth.py` | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| `models.py` | Pydantic request/response models incl. `DiscoverRequest`/`DiscoverResult` |
| `dependencies.py` | Shared FastAPI deps |
| `routes/jobs.py` | `GET /jobs/latest|run|tracked`, `POST /jobs/status|click` |
| `routes/users.py` | `GET/POST /users`, `GET /me` |
| `routes/preferences.py` | Profile, resume upload, LLM settings |
| `routes/companies.py` | `GET /companies`, `POST /companies`, `PATCH /companies/{id}`, `POST /companies/discover` (SSE), `POST /companies/{id}/scrape` |
| `routes/runs.py` | Run management + trigger |
| `routes/stats.py` | Aggregate stats |
| `routes/stream.py` | SSE pipeline event stream |

## Auth

- **JWT**: `Authorization: Bearer <token>`; signed with `APP_SECRET` (or dev fallback). Invalid/missing token → **401** when `APP_SECRET` is set in the environment.
- **Legacy**: If `APP_SECRET` is unset or empty, unauthenticated requests may use `X-User-Id` (omit or `0` → default user via `ensure_default_user_id`).
- **`CurrentUser`**: `id`, `name`, `email`, `active_profile_id` (unchanged shape for route deps).

Registration: `REGISTRATION_TOKEN` must be set to a non-empty value or `POST /auth/register` returns **403**.

## Key Endpoints

```
GET  /jobs/latest          → scored jobs for active profile (min_score=6 default)
GET  /jobs/run/{run_id}    → jobs from specific run
POST /jobs/status          → update tracker status
POST /jobs/click           → promote new → clicked

GET  /companies            → list companies
POST /companies            → create company (allowed `ats_type`: greenhouse, lever, ashby, workday)
PATCH /companies/{id}    → patch careers_url / ats_type (same allowlist)
POST /companies/discover   → SSE stream; discover + add company
POST /companies/{id}/scrape → trigger single company scrape

POST /auth/register        → body: email, name, password, registration_token
POST /auth/login           → body: email, password → JWT
GET  /auth/me              → current user (JWT or legacy)

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
