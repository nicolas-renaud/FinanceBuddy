from pathlib import Path

from financebuddy.db import connect
from financebuddy.projections import apply_events
from financebuddy.schema import initialize_database


def test_apply_events_updates_current_state_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    events = [
        {
            "event_id": "evt-1",
            "run_id": "run-1",
            "event_type": "balance_observed",
            "canonical_account_key": "account:CHK-001",
            "asset_key": None,
            "amount": "1250.50",
            "quantity": None,
            "currency": "EUR",
            "observed_at": "2026-04-11T12:00:00+00:00",
            "payload_json": "{}",
        },
        {
            "event_id": "evt-2",
            "run_id": "run-1",
            "event_type": "position_observed",
            "canonical_account_key": "account:BRK-001",
            "asset_key": "asset:VOO",
            "amount": "510.10",
            "quantity": "12.5",
            "currency": "USD",
            "observed_at": "2026-04-11T12:00:00+00:00",
            "payload_json": "{}",
        },
    ]

    apply_events(db_path, events)

    connection = connect(db_path)
    balance = connection.execute(
        "SELECT amount FROM current_balances WHERE canonical_account_key = ?",
        ("account:CHK-001",),
    ).fetchone()
    position = connection.execute(
        "SELECT quantity FROM current_positions WHERE canonical_account_key = ? AND asset_key = ?",
        ("account:BRK-001", "asset:VOO"),
    ).fetchone()

    assert balance["amount"] == "1250.50"
    assert position["quantity"] == "12.5"
