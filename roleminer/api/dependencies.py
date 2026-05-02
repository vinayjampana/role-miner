"""Shared dependencies + globals for the RoleMiner API."""
import asyncio
import sqlite3
from typing import Generator

import config
from roleminer.registry.db import init_db


# run_id → asyncio.Queue, populated while a run is active
active_runs: dict[int, asyncio.Queue] = {}


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = init_db(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()
