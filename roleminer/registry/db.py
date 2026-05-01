"""SQLite registry for company data and run history."""
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
    output_file TEXT
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
        # Sarvam AI slug uncertain — placeholder, scrape will fail gracefully
        "name": "Sarvam AI",
        "domain": "sarvam.ai",
        "ats_type": "greenhouse",
        "ats_slug": "sarvam-ai",  # UNCERTAIN: update if incorrect
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series A",
    },
    {
        "name": "Zepto",
        "domain": "zeptonow.com",
        "ats_type": "lever",
        "ats_slug": "zepto",  # UNCERTAIN: update if incorrect
        "hq_city": "Mumbai",
        "company_type": "product",
        "funding_stage": "Series F",
    },
    {
        "name": "Slice",
        "domain": "sliceit.com",
        "ats_type": "ashby",
        "ats_slug": "slice",  # UNCERTAIN: update if correct
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series B",
    },
    {
        "name": "PhonePe",
        "domain": "phonepe.com",
        "ats_type": "greenhouse",
        "ats_slug": "phonepe",  # UNCERTAIN: update if incorrect
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series E",
    },
    {
        "name": "Swiggy",
        "domain": "swiggy.com",
        "ats_type": "greenhouse",
        "ats_slug": "swiggy",  # UNCERTAIN: update if incorrect
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Dunzo",
        "domain": "dunzo.com",
        "ats_type": "lever",
        "ats_slug": "dunzo",  # UNCERTAIN: update if incorrect
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series E",
    },
    {
        "name": "Chargebee",
        "domain": "chargebee.com",
        "ats_type": "greenhouse",
        "ats_slug": "chargebee",  # UNCERTAIN: update if incorrect
        "hq_city": "Chennai",
        "company_type": "product",
        "funding_stage": "Series H",
    },
    {
        "name": "Freshworks",
        "domain": "freshworks.com",
        "ats_type": "greenhouse",
        "ats_slug": "freshworks",  # UNCERTAIN: update if incorrect
        "hq_city": "Chennai",
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
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_DDL_COMPANIES)
    conn.execute(_DDL_RUNS)
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
    # always include name
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


def delete_company(conn: sqlite3.Connection, company_id: int) -> None:
    """Delete a company by id."""
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    conn.commit()


def insert_run(conn: sqlite3.Connection, data: dict) -> int:
    """Insert a run record. Returns the new row id."""
    cols = ["timestamp", "jobs_found", "jobs_scored", "tokens_used", "cost_usd", "output_file"]
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
