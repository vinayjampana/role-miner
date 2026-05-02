"""RoleMiner FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging

import config
from roleminer.registry.db import init_db, cleanup_stale_runs
from roleminer.api.routes import companies, jobs, preferences, runs, stats, stream, users

logger = logging.getLogger(__name__)


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

app.include_router(jobs.router)
app.include_router(users.router)
app.include_router(companies.router)
app.include_router(runs.router)
app.include_router(stream.router)
app.include_router(stats.router)
app.include_router(preferences.router)


@app.get("/health")
def health():
    return {"status": "ok"}
