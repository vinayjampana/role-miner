"""User list / create / me — identity is X-User-Id only (no auth)."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends

from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import get_db
from roleminer.api.models import MeOut, SearchProfileOut, UserCreate, UserOut
from roleminer.registry.db import (
    create_user,
    get_active_profile_for_user,
    get_search_profile_row,
    get_user,
    list_users,
)

router = APIRouter(tags=["users"])


def _profile_row_to_out(row: dict) -> SearchProfileOut:
    def _loads(key: str, default):
        try:
            v = json.loads(row.get(key) or "null")
            return v if v is not None else default
        except json.JSONDecodeError:
            return default

    return SearchProfileOut(
        skills=[str(s).strip() for s in _loads("skills_json", []) if str(s).strip()],
        locations=[str(s).strip() for s in _loads("locations_json", []) if str(s).strip()],
        salary_min_lpa=int(row.get("salary_min_lpa") or 0),
        work_mode=[str(m).lower().strip() for m in _loads("work_mode_json", []) if str(m).strip()],
        company_type=[str(c).lower().strip() for c in _loads("company_type_json", []) if str(c).strip()],
        exclude_companies=[str(s).strip() for s in _loads("exclude_companies_json", []) if str(s).strip()],
        notice_days=int(row.get("notice_days") or 0),
        resume_summary=str(row.get("resume_summary") or ""),
    )


@router.get("/users", response_model=list[UserOut])
def list_all_users(db: sqlite3.Connection = Depends(get_db)):
    rows = list_users(db)
    return [
        UserOut(
            id=int(r["id"]),
            name=str(r["name"]),
            email=r.get("email"),
            active_profile_id=int(r["active_profile_id"]) if r.get("active_profile_id") else None,
        )
        for r in rows
    ]


@router.post("/users", response_model=UserOut)
def create_new_user(body: UserCreate, db: sqlite3.Connection = Depends(get_db)):
    name = body.name.strip()
    if not name:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="name required")
    uid = create_user(db, name, body.email)
    row = get_user(db, uid)
    if not row:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="user create failed")
    return UserOut(
        id=uid,
        name=str(row["name"]),
        email=row.get("email"),
        active_profile_id=int(row["active_profile_id"]) if row.get("active_profile_id") else None,
    )


@router.get("/me", response_model=MeOut)
def me(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    urow, prow = get_active_profile_for_user(db, current.id)
    if not urow:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="user not found")
    user_out = UserOut(
        id=int(urow["id"]),
        name=str(urow["name"]),
        email=urow.get("email"),
        active_profile_id=int(urow["active_profile_id"]) if urow.get("active_profile_id") else None,
    )
    profile_out = None
    if prow:
        profile_out = _profile_row_to_out(prow)
    elif urow.get("active_profile_id"):
        pr = get_search_profile_row(db, int(urow["active_profile_id"]))
        if pr:
            profile_out = _profile_row_to_out(pr)
    return MeOut(user=user_out, profile=profile_out)
