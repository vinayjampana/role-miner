# Module: pipeline/

## Files

| File | Purpose |
|---|---|
| `filter.py` | Rule-based filter: location (India), salary, service company |
| `role_filter.py` | Title filter via `_looks_like_job_title` |
| `embedder.py` | OpenRouter embed client; `embed_batched()` |
| `ranker.py` | Semantic rank (ChromaDB cosine) or TF-IDF fallback |
| `scorer.py` | Single LLM batch score call; structured JSON output |
| `classifier.py` | Service company classifier (rule-based) |

## filter.py

Drops jobs by:
- Location not India
- Salary out of profile range (LPA)
- Service company (rule-based via `classifier.py`, not LLM)

## role_filter.py

Wraps `_looks_like_job_title` check.
Drops titles matching marketing/nav patterns.
Keeps jobs where title passes whole-word keyword regex.

## embedder.py

```python
embed_batched(texts: list[str]) -> list[list[float]]
```
Calls `EMBED_MODEL` via `EMBED_BASE_URL`.
Falls back silently if API unavailable (TF-IDF takes over in ranker).

## ranker.py

- If `EMBED_API_KEY` present: ChromaDB cosine similarity vs profile embedding
- Else: TF-IDF `sklearn` vectorizer
- Output: jobs sorted by `rank_score` descending
- Top N (configurable) passed to scorer

## scorer.py

- Input: top 50 ranked jobs + candidate profile
- Single LLM call via `LLM_BASE_URL` / `SCORING_MODEL`
- Prompt: batch JSON with job titles, companies, locations, salary
- Output: `list[{job_url, score: 0-10, reason: str}]`
- Cost budget: <$0.002/run total
