from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)


class DemoBankApiConnector:
    connector_id = "demo_bank_api"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    @classmethod
    def from_fixture_path(cls, fixture_path: Path) -> "DemoBankApiConnector":
        return cls(json.loads(fixture_path.read_text()))

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult:
        captured_at = datetime.fromisoformat(
            self._payload["captured_at"].replace("Z", "+00:00")
        )
        accounts: list[AccountPayload] = []
        balances: list[BalancePayload] = []
        positions: list[PositionPayload] = []

        for item in self._payload["accounts"]:
            source_account_id = item["id"]
            accounts.append(
                AccountPayload(
                    source_account_id=source_account_id,
                    display_name=item["name"],
                    account_type=item["type"],
                    currency=item["currency"],
                )
            )
            if "balance" in item:
                balances.append(
                    BalancePayload(
                        source_account_id=source_account_id,
                        amount=item["balance"],
                        currency=item["currency"],
                        observed_at=captured_at,
                    )
                )
            for position in item.get("positions", []):
                positions.append(
                    PositionPayload(
                        source_account_id=source_account_id,
                        asset_symbol=position["symbol"],
                        asset_name=position["name"],
                        quantity=position["quantity"],
                        unit_price=position.get("unit_price"),
                        currency=position["currency"],
                        observed_at=captured_at,
                    )
                )

        return ConnectorFetchResult(
            accounts=accounts,
            balances=balances,
            positions=positions,
            snapshots=[
                RawSnapshot(
                    snapshot_name="accounts",
                    captured_at=captured_at,
                    payload=self._payload,
                )
            ],
        )
