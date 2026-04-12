from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.db import connect
from financebuddy.schema import initialize_database
from financebuddy.services.crawl_runner import run_crawl


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


def test_run_crawl_persists_crawl_run_metadata(tmp_path: Path) -> None:
    profile = AccessProfile(
        profile_id="alice-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug="alice",
    )
    credentials = RuntimeCredentials(username="alice", password="secret")
    connector = DemoBankApiConnector.from_fixture_path(
        Path("tests/fixtures/demo_bank/accounts.json")
    )

    outcome = run_crawl(
        db_path=tmp_path / "financebuddy.db",
        snapshot_dir=tmp_path / "snapshots",
        connector=connector,
        profile=profile,
        credentials=credentials,
    )

    connection = connect(tmp_path / "financebuddy.db")
    row = connection.execute(
        "SELECT profile_id, connector_id, status, warnings_json FROM crawl_runs WHERE run_id = ?",
        (outcome["run_id"],),
    ).fetchone()

    assert row["profile_id"] == "alice-demo-bank"
    assert row["connector_id"] == "demo_bank_api"
    assert row["status"] == "success"
    assert row["warnings_json"] == "[]"


def test_run_crawl_rolls_back_events_if_crawl_run_insert_fails(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    fixed_run_id = "run-duplicate"
    connection = connect(db_path)
    connection.execute(
        """
        INSERT INTO crawl_runs (
            run_id, profile_id, connector_id, status, started_at, finished_at, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fixed_run_id,
            "existing-profile",
            "demo_bank_api",
            "success",
            "2026-04-11T12:00:00+00:00",
            "2026-04-11T12:01:00+00:00",
            "[]",
        ),
    )
    connection.commit()

    monkeypatch.setattr("financebuddy.services.crawl_runner.uuid.uuid4", lambda: fixed_run_id)

    profile = AccessProfile(
        profile_id="alice-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug="alice",
    )
    credentials = RuntimeCredentials(username="alice", password="secret")
    connector = DemoBankApiConnector.from_fixture_path(
        Path("tests/fixtures/demo_bank/accounts.json")
    )

    try:
        run_crawl(
            db_path=db_path,
            snapshot_dir=tmp_path / "snapshots",
            connector=connector,
            profile=profile,
            credentials=credentials,
        )
    except Exception:
        pass
    else:
        raise AssertionError("expected crawl_run insert failure")

    connection = connect(db_path)
    event_count = connection.execute(
        "SELECT COUNT(*) AS count FROM observation_events WHERE run_id = ?",
        (fixed_run_id,),
    ).fetchone()
    balance_count = connection.execute(
        "SELECT COUNT(*) AS count FROM current_balances"
    ).fetchone()
    position_count = connection.execute(
        "SELECT COUNT(*) AS count FROM current_positions"
    ).fetchone()

    assert event_count["count"] == 0
    assert balance_count["count"] == 0
    assert position_count["count"] == 0
