from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode, urlparse

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

        if self._uses_sim_me_endpoints():
            account_pages = self._fetch_collection_pages(
                "/port/v1/accounts/me",
                headers,
                "accounts",
            )
            snapshots.extend(page.snapshot for page in account_pages)
            account_keys: list[str] = []
            collateral_details_by_account_uic: dict[tuple[str, str], dict[str, Any]] = {}
            for page in account_pages:
                for account in page.items:
                    source_account_id = account["AccountKey"]
                    account_keys.append(source_account_id)
                    accounts.append(
                        AccountPayload(
                            source_account_id=source_account_id,
                            display_name=_account_display_name(account),
                            account_type=_normalize_account_type(account["AccountType"]),
                            currency=account["Currency"],
                        )
                    )

            for account_key in account_keys:
                account = next(
                    item
                    for page in account_pages
                    for item in page.items
                    if item["AccountKey"] == account_key
                )
                balance_payload, balance_snapshot = self._fetch_balance_for_account(
                    account_key,
                    account.get("ClientKey"),
                    headers,
                )
                snapshots.append(balance_snapshot)
                collateral_details_by_account_uic.update(
                    _collateral_details_by_account_uic(account_key, balance_payload)
                )
                balances.append(
                    BalancePayload(
                        source_account_id=account_key,
                        amount=str(balance_payload["CashBalance"]),
                        currency=balance_payload["Currency"],
                        observed_at=_parse_datetime(
                            balance_payload.get("LastUpdated"),
                            fallback=balance_snapshot.captured_at,
                        ),
                    )
                )

            positions_pages = self._fetch_collection_pages(
                "/port/v1/positions/me",
                headers,
                "positions",
            )
            snapshots.extend(page.snapshot for page in positions_pages)
            for page in positions_pages:
                for position in page.items:
                    position_base = position.get("PositionBase", {})
                    position_view = position.get("PositionView", {})
                    display = position.get("DisplayAndFormat", {})
                    collateral_detail = _collateral_detail_for_position(
                        collateral_details_by_account_uic,
                        position_base,
                    )
                    asset_symbol = _position_symbol(position, collateral_detail)
                    observed_at = _parse_datetime(
                        position_base.get("ExecutionTimeOpen"),
                        fallback=page.snapshot.captured_at,
                    )
                    positions.append(
                        PositionPayload(
                            source_account_id=position_base["AccountKey"],
                            asset_symbol=asset_symbol,
                            asset_name=display.get("Description")
                            or collateral_detail.get("Description")
                            or asset_symbol,
                            quantity=str(position_base["Amount"]),
                            unit_price=_position_unit_price(
                                position_base,
                                position_view,
                                collateral_detail,
                            ),
                            currency=_position_currency(position, collateral_detail),
                            observed_at=observed_at,
                        )
                    )
        else:
            account_pages = self._fetch_account_pages(headers)
            snapshots.extend(account_pages.snapshots)
            for account in account_pages.accounts:
                source_account_id = account["AccountKey"]
                accounts.append(
                    AccountPayload(
                        source_account_id=source_account_id,
                        display_name=_account_display_name(account),
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

    def _fetch_balance_for_account(
        self,
        account_key: str,
        client_key: str | None,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], RawSnapshot]:
        query_params = {"AccountKey": account_key}
        if client_key:
            query_params["ClientKey"] = client_key
        payload = self._request_json(
            f"/port/v1/balances?{urlencode(query_params)}",
            headers,
        )
        captured_at = datetime.now(UTC)
        return (
            payload,
            RawSnapshot(
                snapshot_name=f"balance_{_safe_snapshot_segment(account_key)}",
                captured_at=captured_at,
                payload=payload,
            ),
        )

    def _fetch_collection_pages(
        self,
        path: str,
        headers: dict[str, str],
        snapshot_prefix: str,
    ) -> list["_CollectionPage"]:
        pages: list[_CollectionPage] = []
        next_path: str | None = path
        page_index = 1

        while next_path is not None:
            payload = self._request_json(next_path, headers)
            captured_at = datetime.now(UTC)
            pages.append(
                _CollectionPage(
                    items=payload.get("Data", []),
                    snapshot=RawSnapshot(
                        snapshot_name=snapshot_prefix if page_index == 1 else f"{snapshot_prefix}_page_{page_index}",
                        captured_at=captured_at,
                        payload=payload,
                    ),
                )
            )
            next_path = self._normalize_next_path(payload.get("__next"))
            page_index += 1

        return pages

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

    def _uses_sim_me_endpoints(self) -> bool:
        parsed = urlparse(self._base_url)
        return (
            parsed.scheme == "https"
            and parsed.netloc == "gateway.saxobank.com"
            and parsed.path == "/sim/openapi"
        )

    def _normalize_next_path(self, next_path: str | None) -> str | None:
        if next_path is None:
            return None

        base_path = urlparse(self._base_url).path.rstrip("/")
        if base_path and next_path.startswith(f"{base_path}/"):
            return next_path[len(base_path) :]
        return next_path


class _CollectionResult:
    def __init__(self, accounts: list[dict[str, Any]], snapshots: list[RawSnapshot]) -> None:
        self.accounts = accounts
        self.snapshots = snapshots


class _CollectionPage:
    def __init__(self, items: list[dict[str, Any]], snapshot: RawSnapshot) -> None:
        self.items = items
        self.snapshot = snapshot


def _parse_datetime(value: str | None, fallback: datetime | None = None) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    if fallback is not None:
        return fallback
    return datetime.now(UTC)


def _normalize_account_type(raw_account_type: str) -> str:
    return "brokerage"


def _account_display_name(account: dict[str, Any]) -> str:
    return (
        account.get("DisplayName")
        or account.get("Name")
        or account.get("AccountId")
        or account["AccountKey"]
    )


def _position_symbol(
    position: dict[str, Any],
    collateral_detail: dict[str, Any] | None = None,
) -> str:
    collateral_detail = collateral_detail or {}
    display = position.get("DisplayAndFormat", {})
    position_base = position.get("PositionBase", {})
    return (
        display.get("Symbol")
        or collateral_detail.get("Symbol")
        or display.get("Description")
        or collateral_detail.get("Description")
        or _optional_string(position_base.get("Uic"))
        or position.get("PositionId")
        or "unknown"
    )


def _position_currency(
    position: dict[str, Any],
    collateral_detail: dict[str, Any] | None = None,
) -> str:
    display = position.get("DisplayAndFormat", {})
    position_view = position.get("PositionView", {})
    return (
        display.get("Currency")
        or position_view.get("ExposureCurrency")
        or position_view.get("ProfitLossCurrency")
        or "EUR"
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _position_unit_price(
    position_base: dict[str, Any],
    position_view: dict[str, Any],
    collateral_detail: dict[str, Any],
) -> str | None:
    current_price_value = position_view.get("CurrentPrice")
    current_price = _optional_string(current_price_value)
    current_price_decimal = _decimal_from(current_price_value)
    if current_price_decimal is not None and current_price_decimal != Decimal("0"):
        return current_price

    derived_price = _derive_unit_price_from_collateral(
        position_base,
        position_view,
        collateral_detail,
    )
    return derived_price or current_price


def _derive_unit_price_from_collateral(
    position_base: dict[str, Any],
    position_view: dict[str, Any],
    collateral_detail: dict[str, Any],
) -> str | None:
    market_value = _decimal_from(collateral_detail.get("MarketValue"))
    conversion_rate = _decimal_from(position_view.get("ConversionRateCurrent"))
    quantity = _decimal_from(position_base.get("Amount"))

    if market_value is None or conversion_rate is None or quantity is None:
        return None
    if conversion_rate == 0 or quantity == 0:
        return None

    return str(abs(market_value) / abs(conversion_rate) / abs(quantity))


def _collateral_details_by_account_uic(
    account_key: str,
    balance_payload: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    details: dict[tuple[str, str], dict[str, Any]] = {}
    for detail in _instrument_collateral_details(balance_payload):
        uic = _optional_string(detail.get("Uic"))
        if uic is not None:
            details[(account_key, uic)] = detail
    return details


def _instrument_collateral_details(balance_payload: dict[str, Any]) -> list[dict[str, Any]]:
    detail_containers = [
        balance_payload.get("MarginCollateralNotAvailableDetail", {}),
        balance_payload.get("InitialMargin", {}).get("MarginCollateralNotAvailableDetail", {}),
    ]
    details: list[dict[str, Any]] = []
    for container in detail_containers:
        details.extend(container.get("InstrumentCollateralDetails", []))
    return details


def _collateral_detail_for_position(
    collateral_details_by_account_uic: dict[tuple[str, str], dict[str, Any]],
    position_base: dict[str, Any],
) -> dict[str, Any]:
    account_key = position_base.get("AccountKey")
    uic = _optional_string(position_base.get("Uic"))
    if account_key is None or uic is None:
        return {}
    return collateral_details_by_account_uic.get((account_key, uic), {})


def _decimal_from(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _safe_snapshot_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return segment or "account"
