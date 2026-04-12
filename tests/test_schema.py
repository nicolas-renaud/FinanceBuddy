from pathlib import Path

from financebuddy.db import connect
from financebuddy.schema import initialize_database


def test_initialize_database_creates_core_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"

    initialize_database(db_path)

    connection = connect(db_path)
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row[0] for row in rows}

    assert "crawl_runs" in table_names
    assert "observation_events" in table_names
    assert "current_balances" in table_names
    assert "current_positions" in table_names


def test_crawl_runs_table_accepts_warning_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    connection = connect(db_path)
    connection.execute(
        """
        INSERT INTO crawl_runs (
            run_id, profile_id, connector_id, status, started_at, finished_at, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "run-1",
            "alice-demo-bank",
            "demo_bank_api",
            "partial_success",
            "2026-04-11T12:00:00+00:00",
            "2026-04-11T12:01:00+00:00",
            '["one account failed"]',
        ),
    )
    connection.commit()

    row = connection.execute(
        "SELECT status, warnings_json FROM crawl_runs WHERE run_id = ?",
        ("run-1",),
    ).fetchone()

    assert row["status"] == "partial_success"
    assert row["warnings_json"] == '["one account failed"]'
