from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.saxo_bank_api import SaxoBankConnector


FIXTURES_DIR = Path("tests/fixtures/saxo_bank")


class DummyTransport:
    def __init__(self, responses: dict[tuple[str, str], httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.raw_path.decode())
        response = self.responses.get(key)
        if response is None:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        return response


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def build_profile() -> AccessProfile:
    return AccessProfile(
        profile_id="nico-saxo-bank-sim",
        connector_id="saxo_bank_api",
        institution_slug="saxo-bank",
        owner_slug="nico",
    )


def build_credentials(token: str | None = "token-123") -> RuntimeCredentials:
    return RuntimeCredentials(username="nico", password="secret", access_token=token)


def build_connector(responses: dict[tuple[str, str], httpx.Response]) -> SaxoBankConnector:
    client = httpx.Client(transport=httpx.MockTransport(DummyTransport(responses)))
    return SaxoBankConnector(client=client)


def test_connector_maps_recorded_fixture_payloads() -> None:
    accounts_page_1 = load_fixture("accounts_page_1.json")
    accounts_page_2 = load_fixture("accounts_page_2.json")
    balance_acc_1 = load_fixture("balance_acc_1.json")
    balance_acc_2 = load_fixture("balance_acc_2.json")
    positions = load_fixture("positions.json")

    connector = build_connector(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json=accounts_page_1,
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts?page=2"): httpx.Response(
                200,
                json=accounts_page_2,
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC-001/balance"): httpx.Response(
                200,
                json=balance_acc_1,
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC-002/balance"): httpx.Response(
                200,
                json=balance_acc_2,
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/positions"): httpx.Response(
                200,
                json=positions,
                headers={"content-type": "application/json"},
            ),
        }
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert [account.source_account_id for account in result.accounts] == [
        "ACC-001",
        "ACC-002",
    ]
    assert [account.account_type for account in result.accounts] == [
        "brokerage",
        "brokerage",
    ]
    assert [balance.source_account_id for balance in result.balances] == [
        "ACC-001",
        "ACC-002",
    ]
    assert result.positions[0].source_account_id == "ACC-001"
    assert result.positions[0].asset_symbol == "NOVO-B"
    assert result.positions[0].observed_at == datetime(2026, 4, 12, 8, 15, tzinfo=UTC)
    assert result.snapshots[0].snapshot_name == "accounts"


def test_position_timestamp_falls_back_to_capture_time() -> None:
    positions = load_fixture("positions.json")
    positions["Data"][0].pop("LastUpdated", None)

    connector = build_connector(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json=load_fixture("accounts_page_1.json"),
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts?page=2"): httpx.Response(
                200,
                json=load_fixture("accounts_page_2.json"),
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC-001/balance"): httpx.Response(
                200,
                json=load_fixture("balance_acc_1.json"),
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC-002/balance"): httpx.Response(
                200,
                json=load_fixture("balance_acc_2.json"),
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/positions"): httpx.Response(
                200,
                json=positions,
                headers={"content-type": "application/json"},
            ),
        }
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert result.positions[0].observed_at == datetime(2026, 4, 12, 8, 15, tzinfo=UTC)


def test_fetch_requires_access_token() -> None:
    connector = build_connector({})

    with pytest.raises(ValueError, match="access token"):
        connector.fetch(build_profile(), build_credentials(token=None))


def test_missing_account_key_raises() -> None:
    connector = build_connector(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json={"Data": [{"Name": "Missing key"}]},
                headers={"content-type": "application/json"},
            ),
        }
    )

    with pytest.raises(KeyError, match="AccountKey"):
        connector.fetch(build_profile(), build_credentials())


def test_balance_snapshot_name_is_sanitized() -> None:
    connector = build_connector(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC/003", "Name": "Unsafe", "AccountType": "Margin", "Currency": "EUR"}]},
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC/003/balance"): httpx.Response(
                200,
                json={
                    "AccountKey": "ACC/003",
                    "Data": [
                        {
                            "CashBalance": "1.00",
                            "Currency": "EUR",
                            "LastUpdated": "2026-04-12T08:10:00Z",
                        }
                    ],
                },
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/positions"): httpx.Response(
                200,
                json={"Data": []},
                headers={"content-type": "application/json"},
            ),
        }
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert result.snapshots[1].snapshot_name == "balance_ACC_003"
    assert "/" not in result.snapshots[1].snapshot_name
