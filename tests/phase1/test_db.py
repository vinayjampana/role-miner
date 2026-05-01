"""Tests for SQLite registry (db.py)."""
import pytest
from pathlib import Path

from roleminer.registry.db import (
    init_db,
    insert_company,
    get_all_companies,
    get_companies_by_ats,
    update_last_scraped,
    delete_company,
    insert_run,
    get_run_history,
)


@pytest.fixture
def db(tmp_path):
    """Provide a fresh in-memory-like SQLite DB per test."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


def test_insert_and_get_company(db):
    """Insert a company and retrieve it."""
    data = {
        "name": "Razorpay",
        "domain": "razorpay.com",
        "ats_type": "greenhouse",
        "ats_slug": "razorpay",
        "hq_city": "Bangalore",
        "company_type": "product",
    }
    row_id = insert_company(db, data)
    assert isinstance(row_id, int)
    assert row_id > 0

    companies = get_all_companies(db)
    assert len(companies) == 1
    assert companies[0]["name"] == "Razorpay"
    assert companies[0]["ats_type"] == "greenhouse"
    assert companies[0]["ats_slug"] == "razorpay"


def test_get_companies_by_ats(db):
    """Filter companies by ATS type."""
    insert_company(db, {"name": "GH Company", "ats_type": "greenhouse", "ats_slug": "ghco"})
    insert_company(db, {"name": "Lever Company", "ats_type": "lever", "ats_slug": "leverco"})
    insert_company(db, {"name": "Ashby Company", "ats_type": "ashby", "ats_slug": "ashbyco"})

    gh = get_companies_by_ats(db, "greenhouse")
    assert len(gh) == 1
    assert gh[0]["name"] == "GH Company"

    lev = get_companies_by_ats(db, "lever")
    assert len(lev) == 1
    assert lev[0]["name"] == "Lever Company"


def test_update_last_scraped(db):
    """update_last_scraped sets a non-null timestamp."""
    row_id = insert_company(db, {"name": "TestCo"})

    # Before update — last_scraped_at should be None
    companies = get_all_companies(db)
    assert companies[0]["last_scraped_at"] is None

    update_last_scraped(db, row_id)

    companies = get_all_companies(db)
    assert companies[0]["last_scraped_at"] is not None
    assert len(companies[0]["last_scraped_at"]) > 0


def test_delete_company(db):
    """delete_company removes the record."""
    row_id = insert_company(db, {"name": "ToDelete"})
    assert len(get_all_companies(db)) == 1

    delete_company(db, row_id)
    assert get_all_companies(db) == []


def test_delete_nonexistent_company_noop(db):
    """Deleting a non-existent id is a no-op."""
    delete_company(db, 9999)  # should not raise


def test_insert_run_and_get_history(db):
    """Insert run records and retrieve them in reverse order."""
    insert_run(db, {"jobs_found": 100, "jobs_scored": 10, "tokens_used": 5000, "cost_usd": 0.001, "output_file": "output/run1.json"})
    insert_run(db, {"jobs_found": 200, "jobs_scored": 20, "tokens_used": 8000, "cost_usd": 0.002, "output_file": "output/run2.json"})

    history = get_run_history(db, limit=10)
    assert len(history) == 2

    # Newest first
    assert history[0]["jobs_found"] == 200
    assert history[1]["jobs_found"] == 100


def test_get_run_history_respects_limit(db):
    """get_run_history respects the limit parameter."""
    for i in range(5):
        insert_run(db, {"jobs_found": i, "output_file": f"output/run{i}.json"})

    history = get_run_history(db, limit=3)
    assert len(history) == 3


def test_run_timestamp_auto_set(db):
    """Run timestamp is auto-set when not provided."""
    insert_run(db, {"jobs_found": 42})
    history = get_run_history(db, limit=1)
    assert history[0]["timestamp"] is not None


def test_multiple_companies(db):
    """Multiple companies can be inserted and retrieved."""
    names = ["Company A", "Company B", "Company C"]
    for name in names:
        insert_company(db, {"name": name, "ats_type": "greenhouse"})

    all_cos = get_all_companies(db)
    assert len(all_cos) == 3
    retrieved_names = {c["name"] for c in all_cos}
    assert retrieved_names == set(names)
