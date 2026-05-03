"""Lightweight user identity — JWT Bearer or legacy X-User-Id when APP_SECRET is unset."""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
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


def _jwt_secret() -> str:
    return os.getenv("APP_SECRET", "").strip() or "dev-secret-change-me"


def _legacy_auth_allowed() -> bool:
    return not os.getenv("APP_SECRET", "").strip()


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        tok = parts[1].strip()
        return tok or None
    return None


def get_current_user(
    db: sqlite3.Connection = Depends(get_db),
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> CurrentUser:
    bearer = _parse_bearer(authorization)
    if bearer:
        try:
            payload = jwt.decode(bearer, _jwt_secret(), algorithms=["HS256"])
            uid = int(payload["sub"])
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid or expired token") from exc
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
    if _legacy_auth_allowed():
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
    raise HTTPException(status_code=401, detail="authentication required")
