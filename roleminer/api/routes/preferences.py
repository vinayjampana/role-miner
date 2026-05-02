"""Search profile, resume upload, and runtime LLM / env settings (backed by YAML + .env)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, File, HTTPException, UploadFile

import config
from roleminer.api.models import (
    ResumeInfoOut,
    RuntimeSettingsOut,
    RuntimeSettingsUpdate,
    SearchProfileOut,
)
from roleminer.pipeline import embedder

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


@router.get("/profile", response_model=SearchProfileOut)
def get_profile():
    path = config.SEARCH_PROFILE
    if not path.exists():
        raise HTTPException(404, "search_profile.yaml not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.exception("Failed to parse search profile")
        raise HTTPException(500, f"invalid YAML: {exc}") from exc
    return SearchProfileOut.model_validate(raw)


@router.put("/profile", response_model=SearchProfileOut)
def put_profile(body: SearchProfileOut):
    path = config.SEARCH_PROFILE
    try:
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        if existing is None:
            existing = {}
    except Exception:
        existing = {}

    dump = body.model_dump()
    dump["work_mode"] = [m.lower().strip() for m in dump["work_mode"] if str(m).strip()]
    dump["company_type"] = [c.lower().strip() for c in dump["company_type"] if str(c).strip()]
    dump["skills"] = [str(s).strip() for s in dump["skills"] if str(s).strip()]
    dump["locations"] = [str(s).strip() for s in dump["locations"] if str(s).strip()]
    dump["exclude_companies"] = [str(s).strip() for s in dump["exclude_companies"] if str(s).strip()]

    merged = {**existing, **dump}
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# RoleMiner — search profile (saved from UI; safe to edit by hand)\n\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(
            merged,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    logger.info(
        "Profile saved: %d skills, %d locations, salary_min_lpa=%s notice_days=%s resume_summary_chars=%d",
        len(dump["skills"]),
        len(dump["locations"]),
        dump["salary_min_lpa"],
        dump["notice_days"],
        len((dump.get("resume_summary") or "").strip()),
    )
    return SearchProfileOut.model_validate(merged)


@router.get("/profile/resume", response_model=ResumeInfoOut)
def resume_info():
    p = config.RESUME_PDF
    return ResumeInfoOut(has_pdf=p.exists() and p.stat().st_size > 0, path=str(p.name))


@router.post("/profile/resume")
async def upload_resume(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "upload a PDF file")
    dest = config.RESUME_PDF
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    dest.write_bytes(data)
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
