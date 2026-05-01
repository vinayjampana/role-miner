# RoleMiner — Technical Implementation Plan

> India-first job discovery. Scrapes 9 sources, scores against candidate profile, surfaces ranked shortlist via FastAPI + React.

---

## Inputs

```
resume.pdf              — candidate resume (PDF)
search_profile.yaml     — job search preferences (see scope.html §3)
```

No other inputs required. Both files read at run start.

---

## Workflow

```
Bootstrap (run once):
  sources → discover companies → SQLite registry + ChromaDB embeddings

Every run:
  resume + search_profile.yaml
    → embed profile → semantic search registry → top-N companies
    → fan-out: fetch fresh jobs (last 7 days, parallel)
    → aggregate + dedup by URL
    → rule-based filter (date · location · salary · product/service · exclude list)
    → keyword pre-rank (TF-IDF, no LLM)
    → top 50 → LLM batch score + skill gap (ONE API call)
    → write scored_jobs_TIMESTAMP.json
    → FastAPI serves → React dashboard
```

---

## Directory Structure

```
roleminer/
├── main.py                        # CLI: bootstrap | run | serve
├── search_profile.yaml            # user edits this
├── resume.pdf                     # user drops this
├── config.py                      # model config, proxy, paths
├── registry/
│   ├── db.py                      # SQLite CRUD — companies table
│   └── embedder.py                # ChromaDB: embed company profiles + semantic search
├── scrapers/
│   ├── base.py                    # Job dataclass · proxy session · retry · rate limiter · dedup
│   ├── greenhouse.py              # Type A: public REST API
│   ├── lever.py                   # Type A: public REST API
│   ├── ashby.py                   # Type A: public REST API
│   ├── cutshort.py                # Type A: public search API (India-first)
│   ├── wellfound.py               # Type B: GraphQL (India filter applied)
│   ├── yc.py                      # Type B: HTTP scrape
│   ├── iimjobs.py                 # Type B: HTTP scrape (senior India roles)
│   ├── workday.py                 # Type D: unofficial JSON API per company
│   └── naukri.py                  # Type C: Playwright + stealth + proxy
├── pipeline/
│   ├── filter.py                  # rule-based: date, location, salary, product/service, blocklist
│   ├── ranker.py                  # TF-IDF keyword overlap pre-rank
│   ├── scorer.py                  # LLM batch score + skill gap (one call)
│   └── classifier.py             # product vs service company classifier
├── api/
│   ├── main.py                    # FastAPI app
│   ├── routes/
│   │   ├── jobs.py                # GET /jobs, GET /jobs/latest
│   │   ├── stream.py              # GET /stream (SSE — live scrape progress)
│   │   ├── search.py              # POST /search (semantic query → ChromaDB)
│   │   └── stats.py               # GET /stats (token cost, run history)
│   └── models.py                  # Pydantic response models
├── frontend/                      # React + Vite + TypeScript
└── output/                        # scored_jobs_TIMESTAMP.json (ephemeral)
```

---

## Storage

### SQLite — Company Registry

```sql
CREATE TABLE companies (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  domain          TEXT,
  ats_type        TEXT,   -- greenhouse | lever | ashby | cutshort | workday | custom
  careers_url     TEXT,
  ats_slug        TEXT,   -- boards-api.greenhouse.io/v1/boards/{slug}/jobs
  tech_stack      TEXT,   -- JSON array
  location        TEXT,
  hq_city         TEXT,   -- Bangalore | Hyderabad | Mumbai | NCR | Remote
  size_category   TEXT,   -- startup | mid | enterprise
  company_type    TEXT,   -- product | service | consulting
  funding_stage   TEXT,   -- Seed | Series A | B | C | D | Public
  last_scraped_at TEXT,
  embedding_id    TEXT
);
```

### ChromaDB — Company Embeddings

Embed: `{name} {domain} {tech_stack} {location} {size} {funding_stage}`
Query: user search profile text → cosine similarity → top-N companies
One-time per company. Re-embed on registry update.

### JSON — Run Output (ephemeral)

```
output/scored_jobs_TIMESTAMP.json

[{
  "title": "",
  "company": "",
  "url": "",
  "date_posted": "",
  "location": "",
  "work_mode": "remote | hybrid | onsite",
  "salary_lpa": {"min": 30, "max": 50},
  "source": "greenhouse | lever | cutshort | ...",
  "funding_stage": "Series B",
  "has_esop": true,
  "company_type": "product",
  "notice_compatible": true,
  "score": 8,
  "reason": "...",
  "skill_gap": {
    "have": ["React", "TypeScript"],
    "need": ["Rust"],
    "gap": ["Rust"]
  }
}]
```

SQLite `runs` table stores metadata per run (timestamp, jobs found, tokens used, cost) for trend tracking.

---

## Scraper Types

| Type | Sites | Technique | Proxy |
|------|-------|-----------|-------|
| A | Greenhouse · Lever · Ashby · Cutshort | Public REST/JSON API | No |
| B | Wellfound · YC · iimjobs | HTTPX + rotating headers | Datacenter OK |
| C | Naukri | Playwright + playwright-stealth | Residential required |
| D | Workday | Unofficial JSON API | Light |

### Type A — Public APIs

```python
# Greenhouse
GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

# Lever
GET https://api.lever.co/v0/postings/{slug}?mode=json

# Ashby
POST https://api.ashbyhq.com/posting-api/job-board/{slug}
Body: {"limit": 100}

# Cutshort — India-first, zero risk
GET https://cutshort.io/api/public/jobs?skills=React,TypeScript&location=Bangalore
```

### Type B — Wellfound India filter

```python
# Must apply India location filter — without it, results are US-heavy
POST https://wellfound.com/graphql
{
  "query": "...",
  "variables": {
    "locationSlug": "india",
    "remote": true,
    "jobTypes": ["fulltime"]
  }
}
```

### Type D — Workday

```
POST https://{company}.wd{n}.myworkdayjobs.com/wday/cxs/{company}/{tenant}/jobs
Body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "engineer"}
```

Tenant ID: discovered once via browser visit to company careers page → stored in registry. Never re-visits.

### Type C — Naukri

Two strategies (pick one per run):

**Option A — Browser scrape (more data, more risk):**
- Playwright + playwright-stealth patches (canvas, WebGL, navigator)
- Smartproxy residential rotating proxy
- Randomised delays 2–5s
- Secondary account, session cookies persisted across runs
- Max 30 actions per session

**Option B — Email alert parse (zero risk, recommended first):**
- Set up Naukri job alerts for target keywords
- Parse alert emails → extract job links + metadata
- Zero scraping, zero ban risk, structured data
- Limitation: only gets jobs Naukri decides to alert on

Implement Option B first. Fall back to Option A if coverage insufficient.

---

## India-Specific Pipeline

### Product vs Service Classifier (`pipeline/classifier.py`)

```python
SERVICE_SIGNALS = [
    "TCS", "Infosys", "Wipro", "Cognizant", "HCL", "Tech Mahindra",
    "Accenture", "Capgemini", "IBM", "LTIMindtree", "Mphasis",
    "outsourcing", "staffing", "consulting services", "IT services"
]

def classify_company(name: str, description: str) -> str:
    # rule-based first, LLM fallback for ambiguous cases
    ...
```

### India-specific filter rules (`pipeline/filter.py`)

```python
def filter_jobs(jobs, profile):
    return [j for j in jobs if
        j.salary_lpa >= profile.salary_min_lpa           # LPA floor
        and j.location in profile.locations               # India cities + remote
        and j.work_mode in profile.work_mode              # remote/hybrid/onsite
        and j.company_type != "service"                   # if exclude_service=true
        and j.company not in profile.exclude_companies    # blocklist
        and days_since(j.date_posted) <= 7                # freshness
    ]
```

### Notice Period Scoring

Jobs mentioning "immediate joiner" score -1 if candidate notice > 0 days.
Jobs with "30-day notice OK" or no mention = unaffected.
Extracted from JD text via regex before LLM call.

### ESOP Detection

```python
ESOP_PATTERNS = [r"\besop\b", r"\bequity\b", r"\bstock options\b", r"\brsus?\b"]
has_esop = any(re.search(p, jd_text, re.I) for p in ESOP_PATTERNS)
```

---

## Token Strategy

| Step | LLM? | Method |
|------|------|--------|
| Scrape raw jobs | No | API / HTTP |
| Product/service classify | No (rule-based) + LLM fallback | Regex first |
| Notice period extract | No | Regex |
| ESOP detect | No | Regex |
| Salary extract | No | Regex + structured field |
| Date/location/salary filter | No | Rule-based |
| Keyword pre-rank | No | TF-IDF |
| Company semantic search | No | ChromaDB vector search |
| Bootstrap company embed | Once per company | text-embedding-3-small |
| Score + skill gap top 50 | **Once per run** | LLM batch, structured JSON |

### Scoring Prompt (one call)

```
System: You are a senior technical recruiter. Score job fit for an India-based candidate.
        Return a JSON array only. No explanation outside JSON.

User:
  CANDIDATE PROFILE:
  {resume_summary}
  Notice period: {n} days | Prefers: {company_types} | Stack: {stack}

  JOBS (score each 0-10):
  [1] Senior Frontend Engineer | Sarvam AI | Bangalore | Series B | ESOP
      React, TypeScript, LLM tooling experience preferred. 3+ yrs.
  [2] ...
  [50] ...

  Return:
  [{"id":1,"score":9,"reason":"one line","have":["React"],"need":["Rust"],"gap":["Rust"]}]
```

---

## Cost Estimate Per Run

| Step | Tokens | Model | Cost |
|------|--------|-------|------|
| Bootstrap: embed 100 company profiles | ~20,000 | text-embedding-3-small | ~$0.0004 |
| Score + gap 50 jobs — input | ~15,000 | deepseek-v4-flash | ~$0.0008 |
| Score + gap 50 jobs — output | ~2,500 | deepseek-v4-flash | ~$0.0001 |
| **Total per run** | **~17,500** | | **< $0.002 (~₹0.17)** |

Bootstrap one-time: < $0.001

### Models

| Role | Model |
|------|-------|
| Embedding | `text-embedding-3-small` |
| Scoring + gap | `deepseek-v4-flash` or `gpt-4o-mini` |
| Browser agents (Naukri / Workday discovery) | `gpt-4o-mini` |

---

## Frontend (React + TypeScript)

### Tech

```
Vite · React 18 · TypeScript · Zustand · React Query · Recharts · Zod
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stream` | GET SSE | Live scrape progress — one event per source |
| `/jobs/latest` | GET | Latest run scored jobs |
| `/jobs/history` | GET | Past run summaries |
| `/search` | POST | Semantic search → ChromaDB query |
| `/stats` | GET | Token cost, run count, sources hit |

### Key Views

| View | Description |
|------|-------------|
| Dashboard | Ranked job cards · score badge · skill gap tags · filters |
| Live Progress | SSE stream — each source lights up as jobs arrive |
| Job Detail | Full JD · skill radar chart · gap breakdown · apply link |
| Compare | 2–3 jobs side-by-side: score · salary · stack · notice |
| Cluster | UMAP 2D scatter — jobs grouped by domain/seniority |
| Trends | Weekly chart — skill demand over time |
| Cost | Per-run token breakdown and spend history |

---

## Infrastructure

| Component | Service | Cost |
|-----------|---------|------|
| Scraper + API + Frontend | Hetzner CX11 (2vCPU · 2GB) | €4/mo |
| Residential proxy (Naukri) | Smartproxy rotating residential | ~$10/mo |
| ChromaDB + SQLite | Local disk on VPS | Free |
| LLM + Embedding | OpenAI / DeepSeek | < $0.002/run |
| **Total** | | **~$14/mo** |

Docker Compose wraps all services. Single `docker compose up` to run everything.

---

## Implementation Phases

### Phase 1 — Core Pipeline (working end-to-end)
- [ ] `search_profile.yaml` schema + loader
- [ ] `registry/db.py` SQLite company CRUD
- [ ] `scrapers/base.py` Job dataclass · proxy session · retry · rate limiter
- [ ] `scrapers/greenhouse.py` `lever.py` `ashby.py` `cutshort.py` — Type A
- [ ] `pipeline/filter.py` rule-based filter (India-specific rules)
- [ ] `pipeline/classifier.py` product vs service classifier
- [ ] `pipeline/scorer.py` LLM batch score + skill gap
- [ ] `main.py` CLI: `python main.py bootstrap | run`

### Phase 2 — Broader Scraping + Embeddings
- [ ] `scrapers/wellfound.py` GraphQL + India filter
- [ ] `scrapers/yc.py` HTTP scrape
- [ ] `scrapers/iimjobs.py` HTTP scrape
- [ ] `scrapers/workday.py` unofficial API + tenant discovery
- [ ] `registry/embedder.py` ChromaDB embed + semantic search
- [ ] `pipeline/ranker.py` TF-IDF pre-rank
- [ ] India-specific extractions: ESOP, notice period, work mode, funding stage
- [ ] Run history stored to SQLite (for trend tracking)

### Phase 3 — Naukri + Infra
- [ ] `scrapers/naukri.py` email parse (Option B first)
- [ ] Browser scrape fallback (Option A) if coverage insufficient
- [ ] Smartproxy integration
- [ ] VPS deploy (Hetzner)
- [ ] Docker Compose: scraper + FastAPI + ChromaDB + React

### Phase 4 — API + Frontend
- [ ] FastAPI routes: `/stream` (SSE) · `/jobs` · `/search` · `/stats`
- [ ] React: dashboard · job cards · live progress stream
- [ ] Semantic search bar (natural language → ChromaDB)
- [ ] Job detail drawer + skill radar chart (Recharts)
- [ ] Job compare drawer
- [ ] UMAP cluster view
- [ ] Weekly skill trend chart
- [ ] Token cost dashboard

---

## Key Constraints

- Never store full JDs — they expire. Company metadata only, fresh JDs fetched each run.
- All scrapers return same `Job` dataclass — scraper is decoupled from pipeline.
- Dedup by URL before scoring — same job appears on multiple sources.
- Wellfound MUST use India location filter — without it, results skew US-heavy.
- Naukri: email parse first, browser fallback second.
- Workday tenant ID discovered once per company, stored permanently.
- Service company filter is rule-based (fast), not LLM (slow/expensive).
- India salary always in LPA. Never USD internally.
