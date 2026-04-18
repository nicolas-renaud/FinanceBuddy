from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors import saxo_bank_api as saxo_module
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


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2026, 4, 12, 9, 30, tzinfo=tz or UTC)


class SequencedDateTime(datetime):
    values = [
        datetime(2026, 4, 12, 9, 0, tzinfo=UTC),
        datetime(2026, 4, 12, 9, 1, tzinfo=UTC),
        datetime(2026, 4, 12, 9, 2, tzinfo=UTC),
        datetime(2026, 4, 12, 9, 3, tzinfo=UTC),
        datetime(2026, 4, 12, 9, 4, tzinfo=UTC),
        datetime(2026, 4, 12, 9, 5, tzinfo=UTC),
    ]
    index = 0

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = cls.values[cls.index]
        cls.index += 1
        return value.astimezone(tz or UTC)


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


def test_connector_maps_sim_me_payloads() -> None:
    connector = SaxoBankConnector(
        client=httpx.Client(
            transport=httpx.MockTransport(
                DummyTransport(
                    {
                        ("GET", "/sim/openapi/port/v1/accounts/me"): httpx.Response(
                            200,
                            json={
                                "Data": [
                                    {
                                        "AccountKey": "SIM-001",
                                        "ClientKey": "CLIENT-001",
                                        "DisplayName": "SIM Cash Account",
                                        "AccountType": "Cash",
                                        "Currency": "EUR",
                                    }
                                ]
                            },
                            headers={"content-type": "application/json"},
                        ),
                        ("GET", "/sim/openapi/port/v1/balances?AccountKey=SIM-001&ClientKey=CLIENT-001"): httpx.Response(
                            200,
                            json={
                                "AccountKey": "SIM-001",
                                "CashBalance": "2048.75",
                                "Currency": "EUR",
                                "LastUpdated": "2026-04-12T08:20:00Z",
                            },
                            headers={"content-type": "application/json"},
                        ),
                        ("GET", "/sim/openapi/port/v1/positions/me"): httpx.Response(
                            200,
                            json={
                                "Data": [
                                    {
                                        "DisplayAndFormat": {
                                            "Symbol": "NOVO-B",
                                            "Description": "Novo Nordisk B",
                                            "Currency": "DKK",
                                        },
                                        "PositionBase": {
                                            "AccountKey": "SIM-001",
                                            "Amount": 3,
                                            "ExecutionTimeOpen": "2026-04-12T08:25:00Z",
                                        },
                                        "PositionView": {
                                            "CurrentPrice": 987.40,
                                        },
                                    }
                                ]
                            },
                            headers={"content-type": "application/json"},
                        ),
                    }
                )
            )
        ),
        base_url="https://gateway.saxobank.com/sim/openapi",
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert [account.source_account_id for account in result.accounts] == ["SIM-001"]
    assert [account.display_name for account in result.accounts] == ["SIM Cash Account"]
    assert [balance.amount for balance in result.balances] == ["2048.75"]
    assert [balance.source_account_id for balance in result.balances] == ["SIM-001"]
    assert [position.source_account_id for position in result.positions] == ["SIM-001"]
    assert [position.asset_symbol for position in result.positions] == ["NOVO-B"]
    assert [position.quantity for position in result.positions] == ["3"]
    assert [position.unit_price for position in result.positions] == ["987.4"]
    assert [snapshot.snapshot_name for snapshot in result.snapshots] == [
        "accounts",
        "balance_SIM-001",
        "positions",
    ]


def test_connector_enriches_sim_position_from_balance_collateral_details() -> None:
    connector = SaxoBankConnector(
        client=httpx.Client(
            transport=httpx.MockTransport(
                DummyTransport(
                    {
                        ("GET", "/sim/openapi/port/v1/accounts/me"): httpx.Response(
                            200,
                            json={
                                "Data": [
                                    {
                                        "AccountKey": "SIM-001",
                                        "ClientKey": "CLIENT-001",
                                        "AccountId": "22132835",
                                        "AccountType": "Normal",
                                        "Currency": "EUR",
                                    }
                                ]
                            },
                            headers={"content-type": "application/json"},
                        ),
                        ("GET", "/sim/openapi/port/v1/balances?AccountKey=SIM-001&ClientKey=CLIENT-001"): httpx.Response(
                            200,
                            json={
                                "AccountKey": "SIM-001",
                                "CashBalance": 999760.19,
                                "Currency": "EUR",
                                "MarginCollateralNotAvailableDetail": {
                                    "InstrumentCollateralDetails": [
                                        {
                                            "AssetType": "Stock",
                                            "Description": "Apple Inc.",
                                            "MarketValue": 229.705363395,
                                            "Symbol": "AAPL:xnas",
                                            "Uic": 211,
                                        }
                                    ]
                                },
                            },
                            headers={"content-type": "application/json"},
                        ),
                        ("GET", "/sim/openapi/port/v1/positions/me"): httpx.Response(
                            200,
                            json={
                                "Data": [
                                    {
                                        "NetPositionId": "211__Share",
                                        "PositionBase": {
                                            "AccountKey": "SIM-001",
                                            "Amount": 1.0,
                                            "AssetType": "Stock",
                                            "ExecutionTimeOpen": "2026-04-17T13:30:09.499606Z",
                                            "Uic": 211,
                                        },
                                        "PositionView": {
                                            "ConversionRateCurrent": 0.8500365,
                                            "CurrentPrice": 0.0,
                                            "ExposureCurrency": "USD",
                                            "MarketValue": 0.0,
                                        },
                                    }
                                ]
                            },
                            headers={"content-type": "application/json"},
                        ),
                    }
                )
            )
        ),
        base_url="https://gateway.saxobank.com/sim/openapi",
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert len(result.positions) == 1
    position = result.positions[0]
    assert position.asset_symbol == "AAPL:xnas"
    assert position.asset_name == "Apple Inc."
    assert position.quantity == "1.0"
    assert position.currency == "USD"
    assert position.unit_price == "270.23"


def test_connector_follows_sim_me_pagination() -> None:
    SequencedDateTime.index = 0
    original_datetime = saxo_module.datetime
    saxo_module.datetime = SequencedDateTime
    try:
        connector = SaxoBankConnector(
            client=httpx.Client(
                transport=httpx.MockTransport(
                    DummyTransport(
                        {
                            ("GET", "/sim/openapi/port/v1/accounts/me"): httpx.Response(
                                200,
                                json={
                                "Data": [
                                    {
                                        "AccountKey": "SIM-001",
                                        "ClientKey": "CLIENT-001",
                                        "DisplayName": "SIM Cash Account",
                                        "AccountType": "Cash",
                                        "Currency": "EUR",
                                    }
                                ],
                                "__next": "/sim/openapi/port/v1/accounts/me?page=2",
                                },
                                headers={"content-type": "application/json"},
                            ),
                            ("GET", "/sim/openapi/port/v1/accounts/me?page=2"): httpx.Response(
                                200,
                                json={
                                "Data": [
                                    {
                                        "AccountKey": "SIM-002",
                                        "ClientKey": "CLIENT-002",
                                        "DisplayName": "SIM Margin Account",
                                        "AccountType": "Margin",
                                        "Currency": "USD",
                                    }
                                ]
                            },
                                headers={"content-type": "application/json"},
                            ),
                            ("GET", "/sim/openapi/port/v1/balances?AccountKey=SIM-001&ClientKey=CLIENT-001"): httpx.Response(
                                200,
                                json={
                                    "AccountKey": "SIM-001",
                                    "CashBalance": "2048.75",
                                    "Currency": "EUR",
                                },
                                headers={"content-type": "application/json"},
                            ),
                            ("GET", "/sim/openapi/port/v1/balances?AccountKey=SIM-002&ClientKey=CLIENT-002"): httpx.Response(
                                200,
                                json={
                                    "AccountKey": "SIM-002",
                                    "CashBalance": "100.00",
                                    "Currency": "USD",
                                    "LastUpdated": "2026-04-12T08:31:00Z",
                                },
                                headers={"content-type": "application/json"},
                            ),
                            ("GET", "/sim/openapi/port/v1/positions/me"): httpx.Response(
                                200,
                                json={
                                    "Data": [
                                        {
                                            "DisplayAndFormat": {
                                                "Symbol": "NOVO-B",
                                                "Description": "Novo Nordisk B",
                                                "Currency": "DKK",
                                            },
                                            "PositionBase": {
                                                "AccountKey": "SIM-001",
                                                "Amount": 3,
                                            },
                                            "PositionView": {
                                                "CurrentPrice": 987.40,
                                            },
                                        }
                                    ],
                                    "__next": "/sim/openapi/port/v1/positions/me?page=2",
                                },
                                headers={"content-type": "application/json"},
                            ),
                            ("GET", "/sim/openapi/port/v1/positions/me?page=2"): httpx.Response(
                                200,
                                json={
                                    "Data": [
                                        {
                                            "DisplayAndFormat": {
                                                "Symbol": "CSPX",
                                                "Description": "iShares Core S&P 500 UCITS ETF",
                                                "Currency": "USD",
                                            },
                                            "PositionBase": {
                                                "AccountKey": "SIM-002",
                                                "Amount": 1,
                                                "ExecutionTimeOpen": "2026-04-12T08:32:00Z",
                                            },
                                            "PositionView": {
                                                "CurrentPrice": 512.30,
                                            },
                                        }
                                    ]
                                },
                                headers={"content-type": "application/json"},
                            ),
                        }
                    )
                )
            ),
            base_url="https://gateway.saxobank.com/sim/openapi",
        )

        result = connector.fetch(build_profile(), build_credentials())
    finally:
        saxo_module.datetime = original_datetime

    assert [account.source_account_id for account in result.accounts] == [
        "SIM-001",
        "SIM-002",
    ]
    assert [balance.source_account_id for balance in result.balances] == [
        "SIM-001",
        "SIM-002",
    ]
    assert [balance.amount for balance in result.balances] == ["2048.75", "100.00"]
    assert [position.source_account_id for position in result.positions] == [
        "SIM-001",
        "SIM-002",
    ]
    assert result.balances[0].observed_at == datetime(2026, 4, 12, 9, 2, tzinfo=UTC)
    assert result.positions[0].observed_at == datetime(2026, 4, 12, 9, 4, tzinfo=UTC)
    assert result.balances[1].observed_at == datetime(2026, 4, 12, 8, 31, tzinfo=UTC)
    assert result.positions[1].observed_at == datetime(2026, 4, 12, 8, 32, tzinfo=UTC)
    assert [snapshot.snapshot_name for snapshot in result.snapshots] == [
        "accounts",
        "accounts_page_2",
        "balance_SIM-001",
        "balance_SIM-002",
        "positions",
        "positions_page_2",
    ]


def test_position_timestamp_falls_back_to_capture_time(monkeypatch: pytest.MonkeyPatch) -> None:
    positions = load_fixture("positions.json")
    positions["Data"][0].pop("LastUpdated", None)
    monkeypatch.setattr(saxo_module, "datetime", FrozenDateTime)

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

    assert result.positions[0].observed_at == datetime(2026, 4, 12, 9, 30, tzinfo=UTC)
    assert result.snapshots[-1].captured_at == datetime(2026, 4, 12, 9, 30, tzinfo=UTC)


def test_balance_timestamp_falls_back_to_response_capture_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saxo_module, "datetime", FrozenDateTime)

    connector = build_connector(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC-001", "Name": "Primary", "AccountType": "Margin", "Currency": "EUR"}]},
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC-001/balance"): httpx.Response(
                200,
                json={
                    "AccountKey": "ACC-001",
                    "Data": [
                        {
                            "CashBalance": "1250.50",
                            "Currency": "EUR",
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

    assert result.balances[0].observed_at == datetime(2026, 4, 12, 9, 30, tzinfo=UTC)
    assert result.snapshots[1].captured_at == datetime(2026, 4, 12, 9, 30, tzinfo=UTC)


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


def test_balance_request_encodes_account_key_path_segment() -> None:
    transport = DummyTransport(
        {
            ("GET", "/port/v1/accounts"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC/003", "Name": "Unsafe", "AccountType": "Margin", "Currency": "EUR"}]},
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/accounts/ACC%2F003/balance"): httpx.Response(
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
    client = httpx.Client(transport=httpx.MockTransport(transport))
    connector = SaxoBankConnector(client=client)

    result = connector.fetch(build_profile(), build_credentials())

    assert any(
        request.method == "GET" and request.url.raw_path.decode() == "/port/v1/accounts/ACC%2F003/balance"
        for request in transport.requests
    )
    assert result.snapshots[1].snapshot_name == "balance_ACC_003"
    assert "/" not in result.snapshots[1].snapshot_name
