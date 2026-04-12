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


def test_apply_events_updates_existing_projection_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    first_events = [
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
    second_events = [
        {
            "event_id": "evt-3",
            "run_id": "run-2",
            "event_type": "balance_observed",
            "canonical_account_key": "account:CHK-001",
            "asset_key": None,
            "amount": "1300.00",
            "quantity": None,
            "currency": "EUR",
            "observed_at": "2026-04-12T12:00:00+00:00",
            "payload_json": "{}",
        },
        {
            "event_id": "evt-4",
            "run_id": "run-2",
            "event_type": "position_observed",
            "canonical_account_key": "account:BRK-001",
            "asset_key": "asset:VOO",
            "amount": "515.00",
            "quantity": "13.0",
            "currency": "USD",
            "observed_at": "2026-04-12T12:00:00+00:00",
            "payload_json": "{}",
        },
    ]

    apply_events(db_path, first_events)
    apply_events(db_path, second_events)

    connection = connect(db_path)
    balance = connection.execute(
        "SELECT amount, observed_at FROM current_balances WHERE canonical_account_key = ?",
        ("account:CHK-001",),
    ).fetchone()
    position = connection.execute(
        "SELECT quantity, unit_price, observed_at FROM current_positions WHERE canonical_account_key = ? AND asset_key = ?",
        ("account:BRK-001", "asset:VOO"),
    ).fetchone()

    assert balance["amount"] == "1300.00"
    assert balance["observed_at"] == "2026-04-12T12:00:00+00:00"
    assert position["quantity"] == "13.0"
    assert position["unit_price"] == "515.00"
    assert position["observed_at"] == "2026-04-12T12:00:00+00:00"


def test_apply_events_rejects_unknown_event_type(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    events = [
        {
            "event_id": "evt-1",
            "run_id": "run-1",
            "event_type": "unknown_observed",
            "canonical_account_key": "account:CHK-001",
            "asset_key": None,
            "amount": "1250.50",
            "quantity": None,
            "currency": "EUR",
            "observed_at": "2026-04-11T12:00:00+00:00",
            "payload_json": "{}",
        }
    ]

    try:
        apply_events(db_path, events)
    except ValueError as exc:
        assert "unknown_observed" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported event_type")
