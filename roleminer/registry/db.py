"""SQLite registry for company data and run history."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL_COMPANIES = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,
    ats_type        TEXT,
    careers_url     TEXT,
    ats_slug        TEXT,
    tech_stack      TEXT,   -- JSON array string
    location        TEXT,
    hq_city         TEXT,
    size_category   TEXT,
    company_type    TEXT,
    funding_stage   TEXT,
    last_scraped_at TEXT,
    embedding_id    TEXT
);
"""

_DDL_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    jobs_found  INTEGER,
    jobs_scored INTEGER,
    tokens_used INTEGER,
    cost_usd    REAL,
    output_file TEXT,
    status      TEXT DEFAULT 'completed',
    duration_seconds REAL
);
"""

_DDL_RUN_EVENTS = """
CREATE TABLE IF NOT EXISTS run_events (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL,
    ts          TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    source      TEXT,
    data        TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Seed companies — well-known Indian product companies
# ---------------------------------------------------------------------------

SEED_COMPANIES: list[dict] = [
    {
        "name": "Razorpay",
        "domain": "razorpay.com",
        "ats_type": "greenhouse",
        "ats_slug": "razorpay",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series F",
    },
    {
        "name": "Meesho",
        "domain": "meesho.com",
        "ats_type": "greenhouse",
        "ats_slug": "meesho",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series H",
    },
    {
        "name": "Groww",
        "domain": "groww.in",
        "ats_type": "greenhouse",
        "ats_slug": "groww",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series D",
    },
    {
        "name": "CRED",
        "domain": "cred.club",
        "ats_type": "greenhouse",
        "ats_slug": "cred",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series E",
    },
    {
        "name": "BrowserStack",
        "domain": "browserstack.com",
        "ats_type": "greenhouse",
        "ats_slug": "browserstack",
        "hq_city": "Mumbai",
        "company_type": "product",
        "funding_stage": "Series B",
    },
    {
        "name": "Postman",
        "domain": "postman.com",
        "ats_type": "greenhouse",
        "ats_slug": "postman",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series D",
    },
    {
        "name": "Atlassian",
        "domain": "atlassian.com",
        "ats_type": "greenhouse",
        "ats_slug": "atlassian",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Sarvam AI",
        "domain": "sarvam.ai",
        "ats_type": "greenhouse",
        "ats_slug": "sarvam-ai",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series A",
    },
    {
        "name": "Zepto",
        "domain": "zeptonow.com",
        "ats_type": "lever",
        "ats_slug": "zepto",
        "hq_city": "Mumbai",
        "company_type": "product",
        "funding_stage": "Series F",
    },
    {
        "name": "Slice",
        "domain": "sliceit.com",
        "ats_type": "ashby",
        "ats_slug": "slice",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series B",
    },
    {
        "name": "PhonePe",
        "domain": "phonepe.com",
        "ats_type": "greenhouse",
        "ats_slug": "phonepe",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series E",
    },
    {
        "name": "Swiggy",
        "domain": "swiggy.com",
        "ats_type": "greenhouse",
        "ats_slug": "swiggy",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Chargebee",
        "domain": "chargebee.com",
        "ats_type": "greenhouse",
        "ats_slug": "chargebee",
        "hq_city": "Chennai",
        "company_type": "product",
        "funding_stage": "Series H",
    },
    {
        "name": "Freshworks",
        "domain": "freshworks.com",
        "ats_type": "greenhouse",
        "ats_slug": "freshworks",
        "hq_city": "Chennai",
        "company_type": "product",
        "funding_stage": "Public",
    },
    # ----- Workday tenants -----
    {
        "name": "PayPal",
        "domain": "paypal.com",
        "ats_type": "workday",
        "careers_url": "https://paypal.wd1.myworkdayjobs.com/wday/cxs/paypal/jobs/jobs",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Adobe",
        "domain": "adobe.com",
        "ats_type": "workday",
        "careers_url": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Walmart Global Tech",
        "domain": "walmart.com",
        "ats_type": "workday",
        "careers_url": "https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/WalmartExternal/jobs",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialise SQLite database and return connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL_COMPANIES)
    conn.execute(_DDL_RUNS)
    conn.execute(_DDL_RUN_EVENTS)
    # Lightweight migrations for existing DBs missing new columns.
    cur = conn.execute("PRAGMA table_info(runs)")
    existing_cols = {row["name"] for row in cur.fetchall()}
    if "status" not in existing_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN status TEXT DEFAULT 'completed'")
    if "duration_seconds" not in existing_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN duration_seconds REAL")
    conn.commit()
    return conn


def insert_company(conn: sqlite3.Connection, data: dict) -> int:
    """Insert a company record. Returns the new row id."""
    cols = [
        "name", "domain", "ats_type", "careers_url", "ats_slug",
        "tech_stack", "location", "hq_city", "size_category",
        "company_type", "funding_stage", "last_scraped_at", "embedding_id",
    ]
    fields = {k: data.get(k) for k in cols if k in data or data.get(k) is not None}
    fields["name"] = data["name"]

    placeholders = ", ".join("?" for _ in fields)
    column_names = ", ".join(fields.keys())
    values = list(fields.values())

    cur = conn.execute(
        f"INSERT INTO companies ({column_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_all_companies(conn: sqlite3.Connection) -> list[dict]:
    """Return all companies as a list of dicts."""
    cur = conn.execute("SELECT * FROM companies")
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_companies_by_ats(conn: sqlite3.Connection, ats_type: str) -> list[dict]:
    """Return companies filtered by ATS type."""
    cur = conn.execute("SELECT * FROM companies WHERE ats_type = ?", (ats_type,))
    return [_row_to_dict(r) for r in cur.fetchall()]


def update_last_scraped(conn: sqlite3.Connection, company_id: int) -> None:
    """Set last_scraped_at to now for the given company."""
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "UPDATE companies SET last_scraped_at = ? WHERE id = ?",
        (now, company_id),
    )
    conn.commit()


def cleanup_stale_runs(conn: sqlite3.Connection) -> int:
    """Mark runs stuck in 'running' as 'failed'. Returns count fixed."""
    cur = conn.execute(
        "UPDATE runs SET status = 'failed' WHERE status = 'running'"
    )
    conn.commit()
    return cur.rowcount


def update_company_embedding_id(conn: sqlite3.Connection, company_id: int, embedding_id: str) -> None:
    conn.execute("UPDATE companies SET embedding_id = ? WHERE id = ?", (embedding_id, company_id))
    conn.commit()


def delete_company(conn: sqlite3.Connection, company_id: int) -> None:
    """Delete a company by id."""
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    conn.commit()


def insert_run(conn: sqlite3.Connection, data: dict) -> int:
    """Insert a run record. Returns the new row id."""
    cols = ["timestamp", "jobs_found", "jobs_scored", "tokens_used", "cost_usd", "output_file", "status", "duration_seconds"]
    fields = {k: data.get(k) for k in cols}
    if not fields.get("timestamp"):
        fields["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

    placeholders = ", ".join("?" for _ in fields)
    column_names = ", ".join(fields.keys())
    values = list(fields.values())

    cur = conn.execute(
        f"INSERT INTO runs ({column_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_run_history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Return the most recent `limit` runs, newest first."""
    cur = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_run(conn: sqlite3.Connection, run_id: int, fields: dict) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [run_id]
    conn.execute(f"UPDATE runs SET {sets} WHERE id = ?", values)
    conn.commit()


def insert_run_event(
    conn: sqlite3.Connection,
    run_id: int,
    event_type: str,
    data: dict,
    source: str = "",
) -> int:
    """Insert a structured run event. Returns row id."""
    ts = datetime.now(tz=timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO run_events (run_id, ts, event_type, source, data) VALUES (?, ?, ?, ?, ?)",
        (run_id, ts, event_type, source or "", json.dumps(data, default=str)),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_run_events(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM run_events WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    )
    out = []
    for row in cur.fetchall():
        d = _row_to_dict(row)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except json.JSONDecodeError:
            d["data"] = {}
        out.append(d)
    return out
