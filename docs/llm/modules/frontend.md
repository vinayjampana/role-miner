# Module: frontend/

## Stack

React 18 · Vite · TypeScript · React Query · Recharts · Tailwind

## Directory

```
frontend/src/
├── views/          # Dashboard · Tracker · RunLogs · Companies · Settings
├── auth/           # user id for client (X-User-Id header)
├── components/     # JobCard · JobDetail · RunEventStream
├── lib/datetime.ts # IST formatting: formatRunStartedAt, formatEventLogTime
└── api/client.ts   # typed API client incl. discoverCompanies()
```

## Views

| View | Purpose |
|---|---|
| `Dashboard` | Job shortlist, scoring, tracker quick-actions |
| `Tracker` | Kanban/list of tracked jobs by status |
| `RunLogs` | SSE stream viewer, per-run event timeline |
| `Companies` | Company list, inline edit careers_url + ats_type, discover flow |
| `Settings` | Profile, resume upload, LLM config |

## API Client (`api/client.ts`)

Typed wrappers for all backend endpoints.
All requests include `X-User-Id` header from `auth/` module.
Uses React Query for caching + invalidation.

## Date Formatting

All timestamps display in IST.
`formatRunStartedAt(iso)` — run-level display.
`formatEventLogTime(iso)` — event log display (HH:MM:SS IST).

## Dev Setup

```bash
cd frontend && npm run dev   # proxies /api → localhost:8000
```

## Key Patterns

- `RunEventStream` component: SSE consumer, renders event timeline live
- `JobCard` / `JobDetail`: score display, tracker status buttons
- React Query keys include `userId` + `profileId` for per-user cache isolation
