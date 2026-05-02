"""Lightweight user identity — no auth; X-User-Id header selects the row in SQLite."""
from __future__ import annotations

from dataclasses import dataclass

import sqlite3
from fastapi import Depends, Header, HTTPException

from roleminer.api.dependencies import get_db
from roleminer.registry.db import ensure_default_user_id, get_user


@dataclass
class CurrentUser:
    id: int
    name: str
    email: str | None
    active_profile_id: int | None


def get_current_user(
    db: sqlite3.Connection = Depends(get_db),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> CurrentUser:
    raw = (x_user_id or "").strip()
    if not raw or raw == "0":
        uid = ensure_default_user_id(db)
    else:
        try:
            uid = int(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid X-User-Id") from exc
        row = get_user(db, uid)
        if not row:
            raise HTTPException(status_code=404, detail="user not found")
    row = get_user(db, uid)
    if not row:
        raise HTTPException(status_code=404, detail="user not found")
    apid = row.get("active_profile_id")
    return CurrentUser(
        id=int(row["id"]),
        name=str(row["name"]),
        email=row.get("email"),
        active_profile_id=int(apid) if apid is not None else None,
    )
