from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
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
    started_at = datetime.now(UTC).isoformat()
    result = connector.fetch(profile, credentials)
    snapshot_paths = persist_snapshots(snapshot_dir, run_id, result.snapshots)
    events = normalize_events(run_id, result)
    apply_events(db_path, events)

    return {
        "run_id": run_id,
        "started_at": started_at,
        "snapshot_paths": [str(path) for path in snapshot_paths],
        "accounts": result.accounts,
        "balances": result.balances,
        "positions": result.positions,
        "warnings": result.warnings,
    }
