import sqlite3
from pathlib import Path

from financebuddy.schema import initialize_database


def test_initialize_database_creates_core_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"

    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row[0] for row in rows}

    assert "crawl_runs" in table_names
    assert "observation_events" in table_names
    assert "current_balances" in table_names
    assert "current_positions" in table_names
