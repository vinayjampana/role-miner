"""RoleMiner FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from roleminer.registry.db import init_db
from roleminer.api.routes import jobs, runs, stats, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = init_db(config.DB_PATH)
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
app.include_router(runs.router)
app.include_router(stream.router)
app.include_router(stats.router)


@app.get("/health")
def health():
    return {"status": "ok"}
