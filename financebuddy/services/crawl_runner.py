from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.db import transaction
from financebuddy.ingestion import normalize_events
from financebuddy.projections import apply_events, reconcile_current_positions
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
                "running",
                started_at.isoformat(),
                None,
                "[]",
            ),
        )

    try:
        result = connector.fetch(profile, credentials)
        snapshot_paths = persist_snapshots(snapshot_dir, run_id, result.snapshots)
        events = normalize_events(run_id, result)
        status = "partial_success" if result.warnings else "success"
        finished_at = datetime.now(UTC)
        observed_accounts = {
            f"account:{account.source_account_id}": account.account_type
            for account in result.accounts
            if account.source_account_id is not None
        }
        observed_position_keys: dict[str, set[str]] = {}
        for position in result.positions:
            if position.source_account_id is None:
                continue
            canonical_account_key = f"account:{position.source_account_id}"
            observed_position_keys.setdefault(canonical_account_key, set()).add(
                f"asset:{position.asset_symbol}"
            )
        default_observed_at = (
            max(snapshot.captured_at for snapshot in result.snapshots).isoformat()
            if result.snapshots
            else finished_at.isoformat()
        )
        observed_at_by_account = {
            canonical_account_key: default_observed_at
            for canonical_account_key in observed_accounts
        }
        for balance in result.balances:
            if balance.source_account_id is not None:
                observed_at_by_account[f"account:{balance.source_account_id}"] = (
                    balance.observed_at.isoformat()
                )
        for position in result.positions:
            if position.source_account_id is not None:
                observed_at_by_account[f"account:{position.source_account_id}"] = (
                    position.observed_at.isoformat()
                )

        with transaction(db_path) as connection:
            apply_events(db_path, events, connection=connection)
            reconcile_current_positions(
                db_path,
                observed_accounts,
                observed_position_keys,
                observed_at_by_account,
                connection=connection,
            )
            connection.execute(
                """
                UPDATE crawl_runs
                SET status = ?, finished_at = ?, warnings_json = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    finished_at.isoformat(),
                    json.dumps(result.warnings),
                    run_id,
                ),
            )

    except Exception as exc:
        finished_at = datetime.now(UTC)
        with transaction(db_path) as connection:
            connection.execute(
                """
                UPDATE crawl_runs
                SET status = ?, finished_at = ?, warnings_json = ?
                WHERE run_id = ?
                """,
                (
                    "failed",
                    finished_at.isoformat(),
                    json.dumps([str(exc)]),
                    run_id,
                ),
            )
        raise

    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "snapshot_paths": [str(path) for path in snapshot_paths],
        "accounts": result.accounts,
        "balances": result.balances,
        "positions": result.positions,
        "warnings": result.warnings,
    }
