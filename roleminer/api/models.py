"""Pydantic response models for the RoleMiner API."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


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
    tracker_status: str = "new"
    tracker_notes: str = ""


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


class SearchProfileOut(BaseModel):
    """Structured search_profile.yaml — mirrors pipeline expectations."""

    model_config = ConfigDict(extra="ignore")

    skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    salary_min_lpa: int = 0
    work_mode: list[str] = Field(default_factory=list)
    company_type: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    notice_days: int = 0
    resume_summary: str = ""


class RuntimeSettingsOut(BaseModel):
    """Non-secret LLM / infra settings + masked secret hints."""

    llm_base_url: str = ""
    scoring_model: str = ""
    discover_model: str = ""
    embed_base_url: str = ""
    embed_model: str = ""
    scraper_freshness_hours: int = 24
    proxy_url: str = ""
    llm_api_key_set: bool = False
    llm_api_key_hint: str = ""
    embed_api_key_set: bool = False
    embed_api_key_hint: str = ""
    brave_search_api_key_set: bool = False
    brave_search_api_key_hint: str = ""


class RuntimeSettingsUpdate(BaseModel):
    """Partial update: only fields present in the JSON body are written to .env."""

    llm_api_key: str | None = None
    llm_base_url: str | None = None
    scoring_model: str | None = None
    discover_model: str | None = None
    embed_api_key: str | None = None
    embed_base_url: str | None = None
    embed_model: str | None = None
    brave_search_api_key: str | None = None
    scraper_freshness_hours: int | None = None
    proxy_url: str | None = None


class ResumeInfoOut(BaseModel):
    has_pdf: bool
    path: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str | None = None
    active_profile_id: int | None = None


class UserCreate(BaseModel):
    name: str
    email: str | None = None


class MeOut(BaseModel):
    user: UserOut
    profile: SearchProfileOut | None = None


class JobStatusUpdate(BaseModel):
    url: str
    status: str
    notes: str | None = None


class JobClickBody(BaseModel):
    url: str


class CompanyPatch(BaseModel):
    """Partial update: only fields sent in the JSON body are applied."""

    model_config = ConfigDict(extra="forbid")

    careers_url: str | None = Field(
        default=None,
        description="Omit to leave unchanged; empty string clears careers_url.",
    )
    ats_type: str | None = Field(
        default=None,
        description="Omit to leave unchanged; empty string clears ats_type (auto-detect on scrape).",
    )


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
    scrape_strategy: dict | None = None
    strategy_status: str = "active"
