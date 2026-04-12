import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from financebuddy.ingestion import normalize_events
from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)
from financebuddy.snapshots import persist_snapshots


def test_persist_snapshots_writes_json_files(tmp_path: Path) -> None:
    snapshots = [
        RawSnapshot(
            snapshot_name="accounts",
            captured_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
            payload={"accounts": [{"id": "acc-1"}]},
        )
    ]

    written_paths = persist_snapshots(tmp_path, "run-123", snapshots)

    assert len(written_paths) == 1
    content = json.loads(written_paths[0].read_text())
    assert content["accounts"][0]["id"] == "acc-1"


def test_persist_snapshots_rejects_unsafe_snapshot_names(tmp_path: Path) -> None:
    snapshots = [
        RawSnapshot(
            snapshot_name="../outside",
            captured_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
            payload={"accounts": []},
        )
    ]

    with pytest.raises(ValueError, match="snapshot_name"):
        persist_snapshots(tmp_path, "run-123", snapshots)


def test_normalize_events_creates_balance_and_position_events() -> None:
    observed_at = datetime(2026, 4, 11, 12, 0, tzinfo=UTC)
    result = ConnectorFetchResult(
        accounts=[
            AccountPayload(
                source_account_id="BRK-001",
                display_name="Broker",
                account_type="brokerage",
                currency="USD",
            )
        ],
        balances=[
            BalancePayload(
                source_account_id="CHK-001",
                amount="1250.50",
                currency="EUR",
                observed_at=observed_at,
            )
        ],
        positions=[
            PositionPayload(
                source_account_id="BRK-001",
                asset_symbol="VOO",
                asset_name="Vanguard S&P 500 ETF",
                quantity="12.5",
                unit_price="510.10",
                currency="USD",
                observed_at=observed_at,
            )
        ],
    )

    events = normalize_events("run-123", result)

    assert [event["event_type"] for event in events] == [
        "balance_observed",
        "position_observed",
    ]
    assert events[0]["run_id"] == "run-123"
    assert events[0]["canonical_account_key"] == "account:CHK-001"
    assert events[0]["amount"] == "1250.50"
    assert events[0]["quantity"] is None
    assert events[0]["observed_at"] == observed_at.isoformat()
    assert json.loads(events[0]["payload_json"])["source_account_id"] == "CHK-001"
    assert events[1]["asset_key"] == "asset:VOO"
    assert events[1]["canonical_account_key"] == "account:BRK-001"
    assert events[1]["amount"] == "510.10"
    assert events[1]["quantity"] == "12.5"
    assert events[1]["observed_at"] == observed_at.isoformat()
    assert json.loads(events[1]["payload_json"])["asset_symbol"] == "VOO"


def test_normalize_events_rejects_missing_source_account_id() -> None:
    observed_at = datetime(2026, 4, 11, 12, 0, tzinfo=UTC)
    result = ConnectorFetchResult(
        balances=[
            BalancePayload(
                source_account_id=None,
                amount="1250.50",
                currency="EUR",
                observed_at=observed_at,
            )
        ]
    )

    with pytest.raises(ValueError, match="source_account_id"):
        normalize_events("run-123", result)
