"""Company registry endpoints."""
import json
import sqlite3

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from roleminer.api.dependencies import get_db
from roleminer.api.models import CompanyOut, DiscoverRequest
from roleminer.registry.db import get_all_companies
from roleminer.registry.career_finder import discover_companies

router = APIRouter(tags=["companies"])


def _parse_tech_stack(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(db: sqlite3.Connection = Depends(get_db)):
    rows = get_all_companies(db)
    out: list[CompanyOut] = []
    for r in rows:
        out.append(
            CompanyOut(
                id=r["id"],
                name=r["name"],
                domain=r.get("domain"),
                ats_type=r.get("ats_type"),
                careers_url=r.get("careers_url"),
                ats_slug=r.get("ats_slug"),
                tech_stack=_parse_tech_stack(r.get("tech_stack")),
                location=r.get("location"),
                hq_city=r.get("hq_city"),
                size_category=r.get("size_category"),
                company_type=r.get("company_type"),
                funding_stage=r.get("funding_stage"),
                last_scraped_at=r.get("last_scraped_at"),
                embedding_id=r.get("embedding_id"),
            )
        )
    return sorted(out, key=lambda c: c.name.lower())


@router.post("/companies/discover")
async def discover_companies_stream(req: DiscoverRequest, db: sqlite3.Connection = Depends(get_db)):
    """
    Discover career URLs for company names via 4-step flow.
    Streams SSE: one 'result' event per company, then 'done'.
    """
    names = [n.strip() for n in req.names if n.strip()]

    async def generate():
        results = await discover_companies(names, db)
        for r in results:
            yield {"event": "result", "data": json.dumps(r)}
        yield {"event": "done", "data": json.dumps({"total": len(results)})}

    return EventSourceResponse(generate())
