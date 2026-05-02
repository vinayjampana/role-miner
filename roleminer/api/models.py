"""Pydantic response models for the RoleMiner API."""
from typing import Any
from pydantic import BaseModel, Field


class JobOut(BaseModel):
    title: str
    company: str
    url: str
    date_posted: str
    location: str
    source: str
    work_mode: str = "onsite"
    salary_lpa: dict | None = None
    jd_text: str = ""
    funding_stage: str = ""
    has_esop: bool = False
    company_type: str = ""
    notice_compatible: bool = True
    score: int = 0
    reason: str = ""
    skill_gap: dict = Field(default_factory=lambda: {"have": [], "need": [], "gap": []})


class RunSummary(BaseModel):
    id: int
    timestamp: str
    status: str | None = "completed"
    duration_seconds: float | None = None
    jobs_found: int | None = 0
    jobs_scored: int | None = 0
    tokens_used: int | None = 0
    cost_usd: float | None = 0.0
    output_file: str | None = None


class RunEvent(BaseModel):
    id: int
    run_id: int
    ts: str
    event_type: str
    source: str | None = ""
    data: dict


class RunDetail(RunSummary):
    events: list[RunEvent] = []


class StatsOut(BaseModel):
    total_runs: int
    total_jobs_scored: int
    total_tokens: int
    total_cost_usd: float
    sources_hit: dict[str, int]


class TriggerResponse(BaseModel):
    run_id: int


class DiscoverRequest(BaseModel):
    names: list[str]


class DiscoverResult(BaseModel):
    name: str
    found: bool
    careers_url: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    domain: str | None = None
    method: str  # cache | heuristic | search | llm | failed
    already_in_db: bool = False
    company_id: int | None = None


class CompanyOut(BaseModel):
    id: int
    name: str
    domain: str | None = None
    ats_type: str | None = None
    careers_url: str | None = None
    ats_slug: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    location: str | None = None
    hq_city: str | None = None
    size_category: str | None = None
    company_type: str | None = None
    funding_stage: str | None = None
    last_scraped_at: str | None = None
    embedding_id: str | None = None
