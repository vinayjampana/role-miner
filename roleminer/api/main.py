"""RoleMiner FastAPI application."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import logging

import config
from roleminer.registry.db import init_db, cleanup_stale_runs
from roleminer.api.routes import companies, jobs, preferences, runs, stats, stream, users

logger = logging.getLogger(__name__)

_API_PREFIX = "/api"
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = init_db(config.DB_PATH)
    fixed = cleanup_stale_runs(conn)
    if fixed:
        logger.warning("Startup: marked %d stale 'running' runs as 'failed'", fixed)
    conn.close()
    yield


app = FastAPI(title="RoleMiner API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix=_API_PREFIX)
app.include_router(users.router, prefix=_API_PREFIX)
app.include_router(companies.router, prefix=_API_PREFIX)
app.include_router(runs.router, prefix=_API_PREFIX)
app.include_router(stream.router, prefix=_API_PREFIX)
app.include_router(stats.router, prefix=_API_PREFIX)
app.include_router(preferences.router, prefix=_API_PREFIX)


@app.get("/health")
def health():
    return {"status": "ok"}


if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
