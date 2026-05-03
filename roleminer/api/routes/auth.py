"""JWT-based multi-user auth routes."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import get_db
from roleminer.api.models import UserOut
from roleminer.registry.db import (
    create_user_with_password,
    get_user,
    get_user_by_email,
)

router = APIRouter(tags=["auth"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _jwt_secret() -> str:
    return os.getenv("APP_SECRET", "").strip() or "dev-secret-change-me"


def _token_for_user(user_id: int) -> str:
    exp = datetime.now(tz=timezone.utc) + timedelta(days=30)
    return jwt.encode({"sub": str(user_id), "exp": exp}, _jwt_secret(), algorithm="HS256")


class RegisterBody(BaseModel):
    email: str = Field(min_length=1)
    name: str = Field(min_length=1)
    password: str = Field(min_length=1)
    registration_token: str = ""


class RegisterResponse(BaseModel):
    user_id: int
    name: str
    email: str | None = None


class LoginBody(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    token: str
    user_id: int
    name: str
    email: str | None = None


@router.post("/auth/register", response_model=RegisterResponse)
def register(body: RegisterBody, db: sqlite3.Connection = Depends(get_db)):
    expected = os.getenv("REGISTRATION_TOKEN", "")
    if not (expected or "").strip():
        raise HTTPException(status_code=403, detail="Registration disabled")
    if (body.registration_token or "").strip() != expected.strip():
        raise HTTPException(status_code=403, detail="Invalid registration token")
    if get_user_by_email(db, body.email):
        raise HTTPException(status_code=409, detail="email already registered")
    row = db.execute(
        "SELECT id FROM users WHERE lower(trim(name)) = lower(trim(?))",
        (body.name.strip(),),
    ).fetchone()
    if row:
        raise HTTPException(status_code=409, detail="name already taken")
    hashed = _pwd.hash(body.password)
    uid = create_user_with_password(db, body.name.strip(), body.email.strip(), hashed)
    row2 = get_user(db, uid)
    if not row2:
        raise HTTPException(status_code=500, detail="registration failed")
    return RegisterResponse(
        user_id=uid,
        name=str(row2["name"]),
        email=row2.get("email"),
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginBody, db: sqlite3.Connection = Depends(get_db)):
    row = get_user_by_email(db, body.email)
    if not row:
        raise HTTPException(status_code=401, detail="invalid email or password")
    ph = row.get("password_hash")
    if not ph or not _pwd.verify(body.password, ph):
        raise HTTPException(status_code=401, detail="invalid email or password")
    uid = int(row["id"])
    return LoginResponse(
        token=_token_for_user(uid),
        user_id=uid,
        name=str(row["name"]),
        email=row.get("email"),
    )


@router.get("/auth/me", response_model=UserOut)
def auth_me(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    row = get_user(db, current.id)
    if not row:
        raise HTTPException(status_code=404, detail="user not found")
    apid = row.get("active_profile_id")
    return UserOut(
        id=int(row["id"]),
        name=str(row["name"]),
        email=row.get("email"),
        active_profile_id=int(apid) if apid is not None else None,
    )
