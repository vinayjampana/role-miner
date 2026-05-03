# Module: scrapers/

## Files

| File | ATS |
|---|---|
| `greenhouse.py` | Greenhouse (public JSON API) |
| `lever.py` | Lever (public JSON API) |
| `ashby.py` | Ashby (public JSON API) |
| `cutshort.py` | Cutshort |
| `workday.py` | Workday |
| `smartrecruiters.py` | SmartRecruiters |
| `custom.py` | Custom careers pages (Playwright) |
| `base.py` | Base class / shared utilities |

## Job Dataclass (all scrapers return this)

```python
@dataclass
class Job:
    title: str
    company: str
    url: str           # dedup key — UNIQUE per job
    location: str
    salary_lpa: float | None   # LPA always; never USD
    description: str | None    # NOT stored; fetched fresh
    ats: str
    source_company_id: int
```

## Custom Scraper Strategy Order

```
0. XHR network intercept (SPA/React sites)
1. Embedded JSON (__NEXT_DATA__ Next.js)
2. Job card DOM selectors
3. Link heuristics (href patterns)
→ zero-job fallback: find_redirect_via_cta()
   → discovers real ATS portal URL
   → updates careers_url in DB
   → next run uses correct scraper
```

Post-scrape: `validate_custom_scrape()` — cheap LLM call (≤80 tokens) rejects nav/marketing garbage.

## _looks_like_job_title Rules

- Whole-word regex (`_JOB_KEYWORD_RE`)
- Max 10 words
- Blocked by `_MARKETING_RE` + `_CONTENT_SUFFIX_RE`
- Ambiguous single words (`product`, `data`, `sales`) require qualifying role word
- No substring matching

## browser_detect Signal 5

`_JOB_PORTAL_RE` in `browser_detect.py` matches 20+ unsupported ATS portals
(trakstar, workable, breezy, recruitee, iCIMS, Taleo, BambooHR, etc.)
in `<a href>` scan → updates `careers_url` to real listing page.
