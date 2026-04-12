from __future__ import annotations

from pathlib import Path

from financebuddy.db import transaction


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with transaction(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
                run_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                warnings_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS observation_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                canonical_account_key TEXT NOT NULL,
                asset_key TEXT,
                amount TEXT,
                quantity TEXT,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS current_balances (
                canonical_account_key TEXT PRIMARY KEY,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS current_positions (
                canonical_account_key TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                quantity TEXT NOT NULL,
                unit_price TEXT,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (canonical_account_key, asset_key)
            );
            """
        )
