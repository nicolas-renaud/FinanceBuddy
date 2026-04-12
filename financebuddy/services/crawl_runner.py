from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.db import transaction
from financebuddy.ingestion import normalize_events
from financebuddy.projections import apply_events
from financebuddy.schema import initialize_database
from financebuddy.snapshots import persist_snapshots


def run_crawl(
    db_path: Path,
    snapshot_dir: Path,
    connector,
    profile: AccessProfile,
    credentials: RuntimeCredentials,
) -> dict:
    initialize_database(db_path)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    result = connector.fetch(profile, credentials)
    snapshot_paths = persist_snapshots(snapshot_dir, run_id, result.snapshots)
    events = normalize_events(run_id, result)
    apply_events(db_path, events)
    status = "partial_success" if result.warnings else "success"
    finished_at = datetime.now(UTC)

    with transaction(db_path) as connection:
        connection.execute(
            """
            INSERT INTO crawl_runs (
                run_id,
                profile_id,
                connector_id,
                status,
                started_at,
                finished_at,
                warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                profile.profile_id,
                profile.connector_id,
                status,
                started_at.isoformat(),
                finished_at.isoformat(),
                json.dumps(result.warnings),
            ),
        )

    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "snapshot_paths": [str(path) for path in snapshot_paths],
        "accounts": result.accounts,
        "balances": result.balances,
        "positions": result.positions,
        "warnings": result.warnings,
    }
