"""Search profile, resume upload, and runtime LLM / env settings (DB per user + .env)."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
from roleminer.api.auth import CurrentUser, get_current_user
from roleminer.api.dependencies import get_db
from roleminer.api.models import (
    ResumeInfoOut,
    RuntimeSettingsOut,
    RuntimeSettingsUpdate,
    SearchProfileOut,
)
from roleminer.pipeline import embedder
from roleminer.registry.db import (
    get_active_profile_for_user,
    get_search_profile_row,
    set_profile_resume_path,
    update_search_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preferences"])

_ENV_PATH = config.ROOT / ".env"

_ENV_FIELD_MAP: dict[str, str] = {
    "llm_api_key": "LLM_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
    "scoring_model": "SCORING_MODEL",
    "discover_model": "DISCOVER_MODEL",
    "embed_api_key": "EMBED_API_KEY",
    "embed_base_url": "EMBED_BASE_URL",
    "embed_model": "EMBED_MODEL",
    "brave_search_api_key": "BRAVE_SEARCH_API_KEY",
    "scraper_freshness_hours": "SCRAPER_FRESHNESS_HOURS",
    "proxy_url": "PROXY_URL",
}


def _secret_hint(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"…{value[-4:]}"


def _format_env_line(key: str, val: str) -> str:
    if any(c in val for c in ' "\n\t#'):
        esc = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{esc}"'
    return f"{key}={val}"


def _merge_dotenv(path: Path, updates: dict[str, str]) -> None:
    """Merge updates into a .env file; preserve unrelated lines and comments."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text().splitlines()

    seen: set[str] = set()
    out: list[str] = []
    key_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

    for line in lines:
        m = key_re.match(line.strip())
        if m:
            k = m.group(1)
            if k in updates:
                out.append(_format_env_line(k, updates[k]))
                seen.add(k)
                continue
        out.append(line)

    for k, v in updates.items():
        if k not in seen:
            out.append(_format_env_line(k, v))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    logger.info("Wrote %d key(s) to %s", len(updates), path)


def _apply_env_to_process(updates: dict[str, str]) -> None:
    import os

    for k, v in updates.items():
        os.environ[k] = v
    config.sync_from_environ()
    embedder.reset_client()
    logger.info(
        "Runtime config refreshed (keys: %s)",
        ", ".join(sorted(updates.keys())),
    )


def _row_to_search_profile_out(row: dict) -> SearchProfileOut:
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


def _resume_path_for_user(user_id: int) -> Path:
    config.RESUME_DIR.mkdir(parents=True, exist_ok=True)
    return config.RESUME_DIR / f"{user_id}.pdf"


@router.get("/profile", response_model=SearchProfileOut)
def get_profile(
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    _, prow = get_active_profile_for_user(db, current.id)
    if not prow:
        raise HTTPException(404, "no profile for user — create a user first")
    return _row_to_search_profile_out(prow)


@router.put("/profile", response_model=SearchProfileOut)
def put_profile(
    body: SearchProfileOut,
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    urow, prow = get_active_profile_for_user(db, current.id)
    if not urow or not prow or not current.active_profile_id:
        raise HTTPException(404, "no profile for user")
    pid = int(current.active_profile_id)
    pr = get_search_profile_row(db, pid)
    if not pr:
        raise HTTPException(404, "profile row missing")

    dump = body.model_dump()
    dump["work_mode"] = [m.lower().strip() for m in dump["work_mode"] if str(m).strip()]
    dump["company_type"] = [c.lower().strip() for c in dump["company_type"] if str(c).strip()]
    dump["skills"] = [str(s).strip() for s in dump["skills"] if str(s).strip()]
    dump["locations"] = [str(s).strip() for s in dump["locations"] if str(s).strip()]
    dump["exclude_companies"] = [str(s).strip() for s in dump["exclude_companies"] if str(s).strip()]

    update_search_profile(
        db,
        pid,
        skills=dump["skills"],
        locations=dump["locations"],
        salary_min_lpa=int(dump["salary_min_lpa"]),
        work_mode=dump["work_mode"],
        company_type=dump["company_type"],
        exclude_companies=dump["exclude_companies"],
        notice_days=int(dump["notice_days"]),
        resume_summary=str(dump.get("resume_summary") or ""),
    )
    row = get_search_profile_row(db, pid)
    logger.info(
        "Profile saved (user=%s profile_id=%s): %d skills, %d locations",
        current.id,
        pid,
        len(dump["skills"]),
        len(dump["locations"]),
    )
    return _row_to_search_profile_out(row or pr)


@router.get("/profile/resume", response_model=ResumeInfoOut)
def resume_info(current: CurrentUser = Depends(get_current_user)):
    p = _resume_path_for_user(current.id)
    legacy = config.RESUME_PDF
    has_new = p.exists() and p.stat().st_size > 0
    has_legacy = legacy.exists() and legacy.stat().st_size > 0
    return ResumeInfoOut(has_pdf=has_new or has_legacy, path=str(p.name))


@router.post("/profile/resume")
async def upload_resume(
    file: UploadFile = File(...),
    db: sqlite3.Connection = Depends(get_db),
    current: CurrentUser = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "upload a PDF file")
    dest = _resume_path_for_user(current.id)
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    dest.write_bytes(data)
    if current.active_profile_id:
        set_profile_resume_path(db, int(current.active_profile_id), dest.name)
    logger.info("Resume PDF saved: %s (%d bytes)", dest, len(data))
    return {"ok": True, "path": dest.name, "bytes": len(data)}


@router.get("/settings", response_model=RuntimeSettingsOut)
def get_runtime_settings():
    llm = config.LLM_API_KEY
    emb = config.EMBED_API_KEY
    brave = config.BRAVE_SEARCH_API_KEY
    return RuntimeSettingsOut(
        llm_base_url=config.LLM_BASE_URL,
        scoring_model=config.SCORING_MODEL,
        discover_model=config.DISCOVER_MODEL,
        embed_base_url=config.EMBED_BASE_URL,
        embed_model=config.EMBED_MODEL,
        scraper_freshness_hours=config.SCRAPER_FRESHNESS_HOURS,
        proxy_url=config.PROXY_URL,
        llm_api_key_set=bool(llm),
        llm_api_key_hint=_secret_hint(llm),
        embed_api_key_set=bool(emb),
        embed_api_key_hint=_secret_hint(emb),
        brave_search_api_key_set=bool(brave),
        brave_search_api_key_hint=_secret_hint(brave),
    )


@router.put("/settings", response_model=RuntimeSettingsOut)
def put_runtime_settings(body: RuntimeSettingsUpdate):
    payload = body.model_dump(exclude_unset=True, exclude_none=True)
    if not payload:
        logger.info("Settings PUT: no fields to update")
        return get_runtime_settings()

    env_updates: dict[str, str] = {}
    log_model_changed = False
    for field, val in payload.items():
        env_key = _ENV_FIELD_MAP.get(field)
        if not env_key:
            continue
        if field == "scraper_freshness_hours":
            env_updates[env_key] = str(int(val))
        else:
            env_updates[env_key] = str(val).strip()
        if field in ("scoring_model", "discover_model", "embed_model"):
            log_model_changed = True

    if env_updates:
        _merge_dotenv(_ENV_PATH, env_updates)
        _apply_env_to_process(env_updates)

    key_fields = [k for k in env_updates if k.endswith("_API_KEY")]
    logger.info(
        "Runtime settings updated: env_keys=%s models_touched=%s",
        sorted(env_updates.keys()),
        log_model_changed,
    )
    if key_fields:
        logger.info("API key field(s) changed in .env (values not logged): %s", key_fields)

    return get_runtime_settings()
