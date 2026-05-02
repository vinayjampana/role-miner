"""Job listing + tracker — backed by SQLite (jobs, job_runs, job_status)."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import get_db
from roleminer.api.models import JobClickBody, JobOut, JobStatusUpdate
from roleminer.registry.db import (
    get_jobs_for_profile,
    get_jobs_for_run,
    get_run,
    list_tracked_jobs_for_user,
    set_job_tracker_status,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _parse_salary(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_skill_gap(raw: str | None) -> dict:
    if not raw:
        return {"have": [], "need": [], "gap": []}
    try:
        o = json.loads(raw)
        if isinstance(o, dict):
            return {
                "have": list(o.get("have") or []),
                "need": list(o.get("need") or []),
                "gap": list(o.get("gap") or []),
            }
    except json.JSONDecodeError:
        pass
    return {"have": [], "need": [], "gap": []}


def _row_to_job_out(row: dict) -> JobOut:
    rs = row.get("run_score")
    return JobOut(
        title=str(row.get("title") or ""),
        company=str(row.get("company") or ""),
        url=str(row.get("url") or ""),
        date_posted=str(row.get("date_posted") or ""),
        location=str(row.get("location") or ""),
        source=str(row.get("source") or ""),
        work_mode=str(row.get("work_mode") or "onsite"),
        salary_lpa=_parse_salary(row.get("salary_lpa_json")),
        jd_text=str(row.get("jd_text") or ""),
        funding_stage=str(row.get("funding_stage") or ""),
        has_esop=bool(row.get("has_esop")),
        company_type=str(row.get("company_type") or ""),
        notice_compatible=bool(row.get("notice_compatible", True)),
        score=int(rs) if rs is not None else 0,
        reason=str(row.get("reason") or ""),
        skill_gap=_parse_skill_gap(row.get("skill_gap_json")),
        tracker_status=str(row.get("tracker_status") or "new"),
        tracker_notes=str(row.get("tracker_notes") or ""),
    )


def _tracked_row_to_job_out(row: dict) -> JobOut:
    """Row from list_tracked_jobs_for_user (no run_score / reason)."""
    base = dict(row)
    base["run_score"] = None
    base["reason"] = ""
    base["skill_gap_json"] = None
    o = _row_to_job_out(base)
    o.score = 0
    return o


def _assert_run_owned(db: sqlite3.Connection, run_id: int, user_id: int) -> None:
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    ruid = run.get("user_id")
    if ruid is not None and int(ruid) != user_id:
        raise HTTPException(404, "run not found")


@router.get("/latest", response_model=list[JobOut])
def latest_jobs(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
    min_score: int = Query(6, ge=0, le=10, description="Minimum LLM score (default 6)"),
):
    """Jobs from all completed runs for the active profile (deduped, best score per URL)."""
    apid = current.active_profile_id
    if not apid:
        return []
    rows = get_jobs_for_profile(db, current.id, int(apid), min_score=min_score)
    return [_row_to_job_out(r) for r in rows]


@router.get("/run/{run_id}", response_model=list[JobOut])
def jobs_for_run(
    run_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _assert_run_owned(db, run_id, current.id)
    rows = get_jobs_for_run(db, run_id, current.id)
    return [_row_to_job_out(r) for r in rows]


@router.get("/tracked", response_model=list[JobOut])
def tracked_jobs(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    rows = list_tracked_jobs_for_user(db, current.id)
    return [_tracked_row_to_job_out(r) for r in rows]


@router.post("/status", response_model=dict)
def update_status(
    body: JobStatusUpdate,
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    try:
        set_job_tracker_status(db, current.id, url, body.status.strip(), body.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.post("/click", response_model=dict)
def record_click(
    body: JobClickBody,
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    row = db.execute(
        "SELECT status FROM job_status WHERE user_id = ? AND job_url = ?",
        (current.id, url),
    ).fetchone()
    prev = row["status"] if row else "new"
    if prev == "new":
        set_job_tracker_status(db, current.id, url, "clicked", None)
    return {"ok": True}
