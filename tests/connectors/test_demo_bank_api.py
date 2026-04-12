import json
from datetime import datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)


def test_access_profile_keeps_connector_identity() -> None:
    profile = AccessProfile(
        profile_id="alice-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug="alice",
    )

    assert profile.connector_id == "demo_bank_api"
    assert profile.owner_slug == "alice"


def test_runtime_credentials_are_not_persisted() -> None:
    credentials = RuntimeCredentials(username="alice", password="secret")

    assert credentials.password == "secret"


def test_demo_bank_connector_maps_fixture_response() -> None:
    fixture_path = Path("tests/fixtures/demo_bank/accounts.json")

    connector = DemoBankApiConnector.from_fixture_path(fixture_path)
    profile = AccessProfile(
        profile_id="alice-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug="alice",
    )
    credentials = RuntimeCredentials(username="alice", password="secret")

    result = connector.fetch(profile, credentials)

    assert len(result.accounts) == 2
    assert len(result.balances) == 1
    assert len(result.positions) == 1
    assert result.snapshots[0].snapshot_name == "accounts"


def test_connector_models_support_default_and_explicit_construction() -> None:
    captured_at = datetime(2026, 4, 12, 10, 30, 0)
    observed_at = datetime(2026, 4, 12, 10, 31, 0)

    snapshot = RawSnapshot(
        snapshot_name="demo-bank-accounts",
        captured_at=captured_at,
        payload={"accounts": []},
    )
    account = AccountPayload(
        source_account_id="acct-1",
        display_name="Everyday Checking",
        account_type="checking",
        currency="EUR",
    )
    balance = BalancePayload(
        source_account_id="acct-1",
        amount="1250.50",
        currency="EUR",
        observed_at=observed_at,
    )
    position = PositionPayload(
        source_account_id=None,
        asset_symbol="VWRL",
        asset_name="Vanguard FTSE All-World",
        quantity="3",
        unit_price="110.25",
        currency="EUR",
        observed_at=observed_at,
    )
    result = ConnectorFetchResult(
        accounts=[account],
        balances=[balance],
        positions=[position],
        snapshots=[snapshot],
    )

    assert result.accounts == [account]
    assert result.balances == [balance]
    assert result.positions == [position]
    assert result.snapshots == [snapshot]
    assert result.warnings == []
