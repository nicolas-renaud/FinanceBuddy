from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)


class SaxoBankConnector:
    connector_id = "saxo_bank_api"

    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://api.saxo.example",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self._base_url)

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult:
        if not credentials.access_token:
            raise ValueError("Saxo connector requires an access token")

        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        accounts: list[AccountPayload] = []
        balances: list[BalancePayload] = []
        positions: list[PositionPayload] = []
        snapshots: list[RawSnapshot] = []

        account_pages = self._fetch_account_pages(headers)
        snapshots.extend(account_pages.snapshots)
        for account in account_pages.accounts:
            source_account_id = account["AccountKey"]
            accounts.append(
                AccountPayload(
                    source_account_id=source_account_id,
                    display_name=account["Name"],
                    account_type=_normalize_account_type(account["AccountType"]),
                    currency=account["Currency"],
                )
            )

            balance_payload, balance_snapshot = self._fetch_balance(
                source_account_id,
                headers,
            )
            snapshots.append(balance_snapshot)
            balances.append(
                BalancePayload(
                    source_account_id=source_account_id,
                    amount=balance_payload["CashBalance"],
                    currency=balance_payload["Currency"],
                    observed_at=_parse_datetime(
                        balance_payload.get("LastUpdated"),
                        fallback=balance_snapshot.captured_at,
                    ),
                )
            )

        positions_payload, positions_snapshot = self._fetch_positions(headers)
        snapshots.append(positions_snapshot)
        for position in positions_payload:
            observed_at = _parse_datetime(
                position.get("LastUpdated"),
                fallback=positions_snapshot.captured_at,
            )
            positions.append(
                PositionPayload(
                    source_account_id=position["AccountKey"],
                    asset_symbol=position["Symbol"],
                    asset_name=position["Description"],
                    quantity=position["Quantity"],
                    unit_price=position.get("Price"),
                    currency=position["Currency"],
                    observed_at=observed_at,
                )
            )

        return ConnectorFetchResult(
            accounts=accounts,
            balances=balances,
            positions=positions,
            snapshots=snapshots,
        )

    def _fetch_account_pages(
        self,
        headers: dict[str, str],
    ) -> "_CollectionResult":
        accounts: list[dict[str, Any]] = []
        snapshots: list[RawSnapshot] = []
        path: str | None = "/port/v1/accounts"
        page_index = 1

        while path is not None:
            payload = self._request_json(path, headers)
            captured_at = datetime.now(UTC)
            page_accounts = payload.get("Data", [])
            accounts.extend(page_accounts)
            snapshots.append(
                RawSnapshot(
                    snapshot_name="accounts" if page_index == 1 else f"accounts_page_{page_index}",
                    captured_at=captured_at,
                    payload=payload,
                )
            )
            path = payload.get("__next")
            page_index += 1

        return _CollectionResult(accounts=accounts, snapshots=snapshots)

    def _fetch_balance(
        self,
        account_key: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], RawSnapshot]:
        encoded_account_key = quote(account_key, safe="")
        payload = self._request_json(f"/port/v1/accounts/{encoded_account_key}/balance", headers)
        captured_at = datetime.now(UTC)
        return (
            payload["Data"][0],
            RawSnapshot(
                snapshot_name=f"balance_{_safe_snapshot_segment(account_key)}",
                captured_at=captured_at,
                payload=payload,
            ),
        )

    def _fetch_positions(
        self,
        headers: dict[str, str],
    ) -> tuple[list[dict[str, Any]], RawSnapshot]:
        payload = self._request_json("/port/v1/positions", headers)
        captured_at = datetime.now(UTC)
        return (
            payload.get("Data", []),
            RawSnapshot(
                snapshot_name="positions",
                captured_at=captured_at,
                payload=payload,
            ),
        )

    def _request_json(
        self,
        path: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        url = self._absolute_url(path)
        response = self._client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    def _absolute_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"


class _CollectionResult:
    def __init__(self, accounts: list[dict[str, Any]], snapshots: list[RawSnapshot]) -> None:
        self.accounts = accounts
        self.snapshots = snapshots


def _parse_datetime(value: str | None, fallback: datetime | None = None) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    if fallback is not None:
        return fallback
    return datetime.now(UTC)


def _normalize_account_type(raw_account_type: str) -> str:
    return "brokerage"


def _safe_snapshot_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return segment or "account"
