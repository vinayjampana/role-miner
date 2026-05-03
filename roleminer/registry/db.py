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

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    email               TEXT,
    created_at          TEXT NOT NULL,
    active_profile_id   INTEGER
);
"""

_DDL_SEARCH_PROFILES = """
CREATE TABLE IF NOT EXISTS search_profiles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                 INTEGER NOT NULL,
    name                    TEXT NOT NULL DEFAULT 'default',
    skills_json             TEXT NOT NULL DEFAULT '[]',
    locations_json          TEXT NOT NULL DEFAULT '[]',
    salary_min_lpa          INTEGER NOT NULL DEFAULT 0,
    work_mode_json          TEXT NOT NULL DEFAULT '[]',
    company_type_json       TEXT NOT NULL DEFAULT '[]',
    exclude_companies_json  TEXT NOT NULL DEFAULT '[]',
    notice_days             INTEGER NOT NULL DEFAULT 0,
    resume_summary          TEXT NOT NULL DEFAULT '',
    resume_pdf_path         TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

_DDL_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    url                 TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    company             TEXT NOT NULL,
    location            TEXT NOT NULL DEFAULT '',
    date_posted         TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT '',
    work_mode           TEXT NOT NULL DEFAULT 'onsite',
    salary_lpa_json     TEXT,
    jd_text             TEXT NOT NULL DEFAULT '',
    funding_stage       TEXT NOT NULL DEFAULT '',
    has_esop            INTEGER NOT NULL DEFAULT 0,
    company_type        TEXT NOT NULL DEFAULT '',
    notice_compatible   INTEGER NOT NULL DEFAULT 1,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL
);
"""

_DDL_JOB_RUNS = """
CREATE TABLE IF NOT EXISTS job_runs (
    run_id          INTEGER NOT NULL,
    job_url         TEXT NOT NULL,
    rank_score      REAL,
    score           INTEGER,
    reason          TEXT,
    skill_gap_json  TEXT,
    PRIMARY KEY (run_id, job_url),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""

_DDL_JOB_STATUS = """
CREATE TABLE IF NOT EXISTS job_status (
    user_id     INTEGER NOT NULL,
    job_url     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',
    clicked_at  TEXT,
    applied_at  TEXT,
    notes       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, job_url),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

JOB_TRACKER_STATUSES = frozenset({
    "new",
    "clicked",
    "saved",
    "applied",
    "interviewing",
    "rejected",
    "dismissed",
    "archived",
})

# ---------------------------------------------------------------------------
# Seed companies — well-known Indian product companies
# ---------------------------------------------------------------------------

SEED_COMPANIES: list[dict] = [
    {
        "name": "Razorpay",
        "domain": "razorpay.com",
        "ats_type": "greenhouse",
        "ats_slug": "razorpaysoftwareprivatelimited",
        "careers_url": "https://razorpay.com/jobs/",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series F",
    },
    {
        "name": "Meesho",
        "domain": "meesho.com",
        "ats_type": "lever",
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
        "ats_type": "lever",
        "ats_slug": "cred",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series E",
    },
    {
        "name": "BrowserStack",
        "domain": "browserstack.com",
        "ats_type": "workday",
        "careers_url": "https://browserstack.wd3.myworkdayjobs.com/wday/cxs/browserstack/External/jobs",
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
        "ats_type": "lever",
        "ats_slug": "atlassian",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Sarvam AI",
        "domain": "sarvam.ai",
        "ats_type": "ashby",
        "ats_slug": "sarvam",
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
        "ats_type": "greenhouse",
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
        "ats_type": "custom",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Chargebee",
        "domain": "chargebee.com",
        "ats_type": "custom",
        "hq_city": "Chennai",
        "company_type": "product",
        "funding_stage": "Series H",
    },
    {
        "name": "Darwinbox",
        "domain": "darwinbox.in",
        "ats_type": "custom",
        "careers_url": "https://dbx.darwinbox.in/ms/candidatev2/main/careers/allJobs",
        "hq_city": "Hyderabad",
        "company_type": "product",
        "funding_stage": "Unicorn",
    },
    {
        "name": "Freshworks",
        "domain": "freshworks.com",
        "ats_type": "smartrecruiters",
        "ats_slug": "Freshworks",
        "careers_url": "https://careers.smartrecruiters.com/Freshworks",
        "hq_city": "Chennai",
        "company_type": "product",
        "funding_stage": "Public",
    },
    {
        "name": "Vymo",
        "domain": "vymo.com",
        "ats_type": "custom",
        # Public page https://jobs.vymo.com/ iframe-embeds this Darwinbox tenant URL
        "careers_url": "https://vymopeopleconnect.darwinbox.in/ms/candidate/careers",
        "hq_city": "Bangalore",
        "company_type": "product",
        "funding_stage": "Series C",
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
    if "user_id" not in existing_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN user_id INTEGER")
    if "search_profile_id" not in existing_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN search_profile_id INTEGER")

    conn.execute(_DDL_USERS)
    conn.execute(_DDL_SEARCH_PROFILES)
    conn.execute(_DDL_JOBS)
    conn.execute(_DDL_JOB_RUNS)
    conn.execute(_DDL_JOB_STATUS)

    _maybe_seed_default_user(conn)
    _backfill_runs_user_id(conn)
    conn.commit()
    return conn


def _maybe_seed_default_user(conn: sqlite3.Connection) -> None:
    """Create user id=1 'default' with profile if DB has no users; optionally import search_profile.yaml."""
    import config

    row = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
    if row:
        return
    n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if n > 0:
        return
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id, name, email, created_at, active_profile_id) VALUES (1, 'default', NULL, ?, NULL)",
        (now,),
    )
    pid = _insert_blank_profile(conn, 1, now)
    conn.execute("UPDATE users SET active_profile_id = ? WHERE id = 1", (pid,))
    if config.SEARCH_PROFILE.exists():
        try:
            import yaml

            raw = yaml.safe_load(config.SEARCH_PROFILE.read_text(encoding="utf-8")) or {}
            _write_profile_from_yaml_dict(conn, pid, raw, now)
        except Exception:
            pass
    conn.commit()


def _insert_blank_profile(conn: sqlite3.Connection, user_id: int, now: str) -> int:
    conn.execute(
        """
        INSERT INTO search_profiles (
            user_id, name, skills_json, locations_json, salary_min_lpa,
            work_mode_json, company_type_json, exclude_companies_json,
            notice_days, resume_summary, created_at, updated_at
        ) VALUES (?, 'default', '[]', '[]', 0, '[]', '[]', '[]', 0, '', ?, ?)
        """,
        (user_id, now, now),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _write_profile_from_yaml_dict(conn: sqlite3.Connection, profile_id: int, raw: dict, now: str) -> None:
    skills = [str(s).strip() for s in (raw.get("skills") or []) if str(s).strip()]
    locations = [str(s).strip() for s in (raw.get("locations") or []) if str(s).strip()]
    wm = [m.lower().strip() for m in (raw.get("work_mode") or []) if str(m).strip()]
    ct = [c.lower().strip() for c in (raw.get("company_type") or []) if str(c).strip()]
    ex = [str(s).strip() for s in (raw.get("exclude_companies") or []) if str(s).strip()]
    conn.execute(
        """
        UPDATE search_profiles SET
            skills_json = ?, locations_json = ?, salary_min_lpa = ?,
            work_mode_json = ?, company_type_json = ?, exclude_companies_json = ?,
            notice_days = ?, resume_summary = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(skills),
            json.dumps(locations),
            int(raw.get("salary_min_lpa") or 0),
            json.dumps(wm),
            json.dumps(ct),
            json.dumps(ex),
            int(raw.get("notice_days") or 0),
            str(raw.get("resume_summary") or ""),
            now,
            profile_id,
        ),
    )


def _backfill_runs_user_id(conn: sqlite3.Connection) -> None:
    """Attach legacy runs (NULL user_id) to user 1 if that user exists."""
    row = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
    if not row:
        return
    conn.execute("UPDATE runs SET user_id = 1 WHERE user_id IS NULL")


def ensure_default_user_id(conn: sqlite3.Connection) -> int:
    """Return user id 1, creating default user + profile if needed."""
    _maybe_seed_default_user(conn)
    row = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
    if row:
        return 1
    row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id, name, email, created_at, active_profile_id) VALUES (1, 'default', NULL, ?, NULL)",
        (now,),
    )
    pid = _insert_blank_profile(conn, 1, now)
    conn.execute("UPDATE users SET active_profile_id = ? WHERE id = 1", (pid,))
    conn.commit()
    return 1


def list_users(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT * FROM users ORDER BY id ASC")
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_user(conn: sqlite3.Connection, name: str, email: str | None = None) -> int:
    now = datetime.now(tz=timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO users (name, email, created_at, active_profile_id) VALUES (?, ?, ?, NULL)",
        (name.strip(), (email or "").strip() or None, now),
    )
    uid = int(cur.lastrowid)
    pid = _insert_blank_profile(conn, uid, now)
    conn.execute("UPDATE users SET active_profile_id = ? WHERE id = ?", (pid, uid))
    conn.commit()
    return uid


def get_search_profile_row(conn: sqlite3.Connection, profile_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM search_profiles WHERE id = ?", (profile_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def search_profile_row_to_pipeline_dict(row: dict) -> dict:
    def _loads(s: str, default):
        try:
            return json.loads(s or "")
        except json.JSONDecodeError:
            return default

    return {
        "skills": _loads(row.get("skills_json"), []),
        "locations": _loads(row.get("locations_json"), []),
        "salary_min_lpa": int(row.get("salary_min_lpa") or 0),
        "work_mode": _loads(row.get("work_mode_json"), []),
        "company_type": _loads(row.get("company_type_json"), []),
        "exclude_companies": _loads(row.get("exclude_companies_json"), []),
        "notice_days": int(row.get("notice_days") or 0),
        "resume_summary": str(row.get("resume_summary") or ""),
    }


def get_active_profile_for_user(conn: sqlite3.Connection, user_id: int) -> tuple[dict | None, dict | None]:
    """Returns (user_row, profile_row) or (user_row, None)."""
    u = get_user(conn, user_id)
    if not u:
        return None, None
    apid = u.get("active_profile_id")
    if not apid:
        return u, None
    pr = get_search_profile_row(conn, int(apid))
    return u, pr


def update_search_profile(
    conn: sqlite3.Connection,
    profile_id: int,
    skills: list[str],
    locations: list[str],
    salary_min_lpa: int,
    work_mode: list[str],
    company_type: list[str],
    exclude_companies: list[str],
    notice_days: int,
    resume_summary: str,
) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE search_profiles SET
            skills_json = ?, locations_json = ?, salary_min_lpa = ?,
            work_mode_json = ?, company_type_json = ?, exclude_companies_json = ?,
            notice_days = ?, resume_summary = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(skills),
            json.dumps(locations),
            salary_min_lpa,
            json.dumps(work_mode),
            json.dumps(company_type),
            json.dumps(exclude_companies),
            notice_days,
            resume_summary,
            now,
            profile_id,
        ),
    )
    conn.commit()


def set_profile_resume_path(conn: sqlite3.Connection, profile_id: int, path: str) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "UPDATE search_profiles SET resume_pdf_path = ?, updated_at = ? WHERE id = ?",
        (path, now, profile_id),
    )
    conn.commit()


def upsert_job(conn: sqlite3.Connection, job: dict) -> None:
    """Upsert a job row from a Job-like dict (url, title, company, …)."""
    now = datetime.now(tz=timezone.utc).isoformat()
    url = job["url"]
    sal = job.get("salary_lpa")
    sal_json = json.dumps(sal) if sal is not None else None
    row = conn.execute("SELECT url FROM jobs WHERE url = ?", (url,)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE jobs SET
                title = ?, company = ?, location = ?, date_posted = ?, source = ?, work_mode = ?,
                salary_lpa_json = ?, jd_text = ?, funding_stage = ?, has_esop = ?,
                company_type = ?, notice_compatible = ?, last_seen_at = ?
            WHERE url = ?
            """,
            (
                job.get("title") or "",
                job.get("company") or "",
                job.get("location") or "",
                job.get("date_posted") or "",
                job.get("source") or "",
                job.get("work_mode") or "onsite",
                sal_json,
                job.get("jd_text") or "",
                job.get("funding_stage") or "",
                1 if job.get("has_esop") else 0,
                job.get("company_type") or "",
                1 if job.get("notice_compatible", True) else 0,
                now,
                url,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO jobs (
                url, title, company, location, date_posted, source, work_mode,
                salary_lpa_json, jd_text, funding_stage, has_esop, company_type,
                notice_compatible, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                job.get("title") or "",
                job.get("company") or "",
                job.get("location") or "",
                job.get("date_posted") or "",
                job.get("source") or "",
                job.get("work_mode") or "onsite",
                sal_json,
                job.get("jd_text") or "",
                job.get("funding_stage") or "",
                1 if job.get("has_esop") else 0,
                job.get("company_type") or "",
                1 if job.get("notice_compatible", True) else 0,
                now,
                now,
            ),
        )
    conn.commit()


def replace_job_runs_for_run(
    conn: sqlite3.Connection,
    run_id: int,
    ranked_jobs: list[dict],
    rank_scores: list[float],
) -> None:
    conn.execute("DELETE FROM job_runs WHERE run_id = ?", (run_id,))
    for job, rs in zip(ranked_jobs, rank_scores):
        conn.execute(
            """
            INSERT INTO job_runs (run_id, job_url, rank_score, score, reason, skill_gap_json)
            VALUES (?, ?, ?, NULL, NULL, NULL)
            """,
            (run_id, job["url"], float(rs)),
        )
    conn.commit()


def update_job_runs_scores(
    conn: sqlite3.Connection,
    run_id: int,
    scored: list[dict],
) -> None:
    for sj in scored:
        conn.execute(
            """
            UPDATE job_runs SET score = ?, reason = ?, skill_gap_json = ?
            WHERE run_id = ? AND job_url = ?
            """,
            (
                int(sj.get("score") or 0),
                str(sj.get("reason") or ""),
                json.dumps(sj.get("skill_gap") or {"have": [], "need": [], "gap": []}),
                run_id,
                sj["url"],
            ),
        )
    conn.commit()


def get_latest_completed_run_id_for_user(conn: sqlite3.Connection, user_id: int) -> int | None:
    cur = conn.execute(
        """
        SELECT id FROM runs
        WHERE user_id = ? AND status = 'completed'
        ORDER BY id DESC LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def get_jobs_for_run(conn: sqlite3.Connection, run_id: int, user_id: int) -> list[dict]:
    cur = conn.execute(
        """
        SELECT j.*, jr.rank_score, jr.score AS run_score, jr.reason, jr.skill_gap_json,
               COALESCE(js.status, 'new') AS tracker_status,
               js.clicked_at, js.applied_at, js.notes AS tracker_notes
        FROM jobs j
        INNER JOIN job_runs jr ON jr.job_url = j.url AND jr.run_id = ?
        LEFT JOIN job_status js ON js.job_url = j.url AND js.user_id = ?
        ORDER BY jr.rank_score DESC
        """,
        (run_id, user_id),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_jobs_for_profile(
    conn: sqlite3.Connection,
    user_id: int,
    search_profile_id: int,
    *,
    min_score: int = 6,
) -> list[dict]:
    """
    All jobs from any completed run for this user + profile (including legacy runs
    with NULL search_profile_id). Per job URL: keep the highest LLM score seen;
    tie-break to the newest run. Only rows with score >= min_score.
    """
    cur = conn.execute(
        """
        WITH qualifying AS (
          SELECT jr.job_url, MAX(jr.score) AS best_score
          FROM job_runs jr
          INNER JOIN runs r ON r.id = jr.run_id
          WHERE r.user_id = ?
            AND r.status = 'completed'
            AND (r.search_profile_id = ? OR r.search_profile_id IS NULL)
            AND jr.score IS NOT NULL AND jr.score >= ?
          GROUP BY jr.job_url
        ),
        picked AS (
          SELECT jr.job_url, MAX(jr.run_id) AS pick_run
          FROM job_runs jr
          INNER JOIN qualifying q ON q.job_url = jr.job_url AND jr.score = q.best_score
          INNER JOIN runs r ON r.id = jr.run_id
          WHERE r.user_id = ?
            AND r.status = 'completed'
            AND (r.search_profile_id = ? OR r.search_profile_id IS NULL)
          GROUP BY jr.job_url
        )
        SELECT j.*, jr.rank_score, jr.score AS run_score, jr.reason, jr.skill_gap_json,
               COALESCE(js.status, 'new') AS tracker_status,
               js.clicked_at, js.applied_at, js.notes AS tracker_notes
        FROM picked p
        INNER JOIN job_runs jr ON jr.job_url = p.job_url AND jr.run_id = p.pick_run
        INNER JOIN jobs j ON j.url = jr.job_url
        LEFT JOIN job_status js ON js.job_url = j.url AND js.user_id = ?
        ORDER BY jr.score DESC, jr.rank_score DESC
        """,
        (user_id, search_profile_id, min_score, user_id, search_profile_id, user_id),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def set_job_tracker_status(
    conn: sqlite3.Connection,
    user_id: int,
    job_url: str,
    status: str,
    notes: str | None = None,
) -> None:
    if status not in JOB_TRACKER_STATUSES:
        raise ValueError(f"invalid status: {status}")
    now = datetime.now(tz=timezone.utc).isoformat()
    row = conn.execute(
        "SELECT clicked_at, applied_at FROM job_status WHERE user_id = ? AND job_url = ?",
        (user_id, job_url),
    ).fetchone()
    clicked_at = row["clicked_at"] if row else None
    applied_at = row["applied_at"] if row else None
    if status == "clicked" and not clicked_at:
        clicked_at = now
    if status == "applied" and not applied_at:
        applied_at = now
    if row:
        if notes is not None:
            conn.execute(
                """
                UPDATE job_status SET status = ?, notes = ?, updated_at = ?,
                    clicked_at = COALESCE(?, clicked_at), applied_at = COALESCE(?, applied_at)
                WHERE user_id = ? AND job_url = ?
                """,
                (status, notes, now, clicked_at, applied_at, user_id, job_url),
            )
        else:
            conn.execute(
                """
                UPDATE job_status SET status = ?, updated_at = ?,
                    clicked_at = COALESCE(?, clicked_at), applied_at = COALESCE(?, applied_at)
                WHERE user_id = ? AND job_url = ?
                """,
                (status, now, clicked_at, applied_at, user_id, job_url),
            )
    else:
        conn.execute(
            """
            INSERT INTO job_status (user_id, job_url, status, clicked_at, applied_at, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, job_url, status, clicked_at, applied_at, notes if notes is not None else "", now),
        )
    conn.commit()


def list_tracked_jobs_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    cur = conn.execute(
        """
        SELECT j.*, js.status AS tracker_status, js.clicked_at, js.applied_at, js.notes AS tracker_notes, js.updated_at AS tracker_updated_at
        FROM job_status js
        INNER JOIN jobs j ON j.url = js.job_url
        WHERE js.user_id = ?
        ORDER BY js.updated_at DESC
        """,
        (user_id,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


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


def clear_scrape_freshness(conn: sqlite3.Connection) -> int:
    """Clear last_scraped_at for every company so the next run ignores freshness skips."""
    cur = conn.execute("UPDATE companies SET last_scraped_at = NULL")
    conn.commit()
    return cur.rowcount  # type: ignore[return-value]


def update_company_fields(conn: sqlite3.Connection, company_id: int, fields: dict) -> None:
    """Patch company row; only keys present in `fields` are updated."""
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE companies SET {sets} WHERE id = ?", [*fields.values(), company_id])
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
    cols = [
        "timestamp", "jobs_found", "jobs_scored", "tokens_used", "cost_usd", "output_file",
        "status", "duration_seconds", "user_id", "search_profile_id",
    ]
    fields = {k: data[k] for k in cols if k in data and data[k] is not None}
    if "timestamp" not in fields:
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


def get_run_history(conn: sqlite3.Connection, limit: int = 10, user_id: int | None = None) -> list[dict]:
    """Return the most recent `limit` runs, newest first. When user_id is set, only that user's runs."""
    if user_id is not None:
        cur = conn.execute(
            "SELECT * FROM runs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
    else:
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
