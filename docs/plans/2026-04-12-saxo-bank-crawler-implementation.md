# Saxo Bank Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixture-first Saxo Bank crawler that prompts for a read-only access token, fetches accounts, cash balances, and stock/ETF positions through a thin connector, and persists the results through the existing FinanceBuddy event-log-first pipeline.

**Architecture:** Extend the current single-connector demo CLI into a connector-selecting crawl command, add a direct `httpx`-based Saxo connector with HTTP client injection for fixture-first tests, and keep ingestion and projections on the existing `ConnectorFetchResult` contract. The first slice stores raw Saxo payloads as snapshots, maps only the supported balance and position fields, and defers OAuth, transactions, and cost basis.

**Tech Stack:** Python 3.12, `uv`, Typer, pytest, HTTPX, Pydantic v2, SQLite

---

## File Structure

Planned file changes for this slice:

- Modify: `pyproject.toml`
  Add any missing HTTP dependency needed by the Saxo connector tests and runtime.
- Modify: `financebuddy/cli.py`
  Replace the demo-only crawl command with a connector-selecting command that supports the existing demo fixture path and the new Saxo path.
- Modify: `financebuddy/connectors/base.py`
  Add an optional token field to runtime credentials while preserving the current password behavior for the demo connector.
- Create: `financebuddy/connectors/saxo_bank_api.py`
  Implement the thin direct HTTP Saxo connector with snapshot mapping and pagination handling.
- Modify: `financebuddy/connectors/__init__.py`
  Export the Saxo connector if the module currently serves as a registry surface.
- Modify: `financebuddy/models.py`
  Add any minimal identifier fields needed to support stable Saxo position mapping without breaking the current event flow.
- Modify: `financebuddy/ingestion.py`
  Keep the current event contract intact and adjust only if model changes require it.
- Modify: `financebuddy/services/reporting.py`
  Update summary formatting only if new account types or identifiers make the current output confusing.
- Modify: `README.md`
  Document the Saxo fixture-first crawl path and token entry behavior.
- Create: `tests/fixtures/saxo_bank/accounts_page_1.json`
  First page of Saxo-style accounts fixture.
- Create: `tests/fixtures/saxo_bank/accounts_page_2.json`
  Second page fixture for `__next` pagination coverage.
- Create: `tests/fixtures/saxo_bank/balance_acc_1.json`
  Per-account cash balance fixture.
- Create: `tests/fixtures/saxo_bank/balance_acc_2.json`
  Additional balance fixture for a second account.
- Create: `tests/fixtures/saxo_bank/positions.json`
  Positions fixture containing supported and unsupported rows.
- Create: `tests/connectors/test_saxo_bank_api.py`
  Unit tests for Saxo connector mapping, pagination, warnings, and failures.
- Modify: `tests/test_cli.py`
  Add CLI coverage for Saxo token prompting and env-variable fallback.
- Modify: `tests/test_smoke.py`
  Add a Saxo fixture-backed smoke path if the current smoke tests cover end-to-end crawl behavior.

### Task 1: Add Runtime Credential Support For Token-Based Connectors

**Files:**
- Modify: `financebuddy/connectors/base.py`
- Modify: `tests/connectors/test_demo_bank_api.py`

- [ ] **Step 1: Write the failing credential-model test**

Add this test to `tests/connectors/test_demo_bank_api.py` below the existing runtime credential test:

```python
def test_runtime_credentials_support_optional_access_token() -> None:
    credentials = RuntimeCredentials(
        username="alice",
        password="secret",
        access_token="token-123",
    )

    assert credentials.access_token == "token-123"
    assert "token-123" not in repr(credentials)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py::test_runtime_credentials_support_optional_access_token -v`
Expected: FAIL with `TypeError` or `AttributeError` because `RuntimeCredentials` does not yet expose `access_token`

- [ ] **Step 3: Write minimal implementation**

Update `financebuddy/connectors/base.py` to:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from financebuddy.models import ConnectorFetchResult


@dataclass(frozen=True)
class AccessProfile:
    profile_id: str
    connector_id: str
    institution_slug: str
    owner_slug: str


@dataclass(frozen=True)
class RuntimeCredentials:
    username: str
    password: str = field(default="", repr=False)
    access_token: str = field(default="", repr=False)


class Connector(Protocol):
    connector_id: str

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult: ...
```

- [ ] **Step 4: Run targeted tests to verify they pass**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/connectors/base.py tests/connectors/test_demo_bank_api.py
git commit -m "feat: add token support to runtime credentials"
```

### Task 2: Add Saxo Fixtures And Connector Unit Tests

**Files:**
- Create: `tests/fixtures/saxo_bank/accounts_page_1.json`
- Create: `tests/fixtures/saxo_bank/accounts_page_2.json`
- Create: `tests/fixtures/saxo_bank/balance_acc_1.json`
- Create: `tests/fixtures/saxo_bank/balance_acc_2.json`
- Create: `tests/fixtures/saxo_bank/positions.json`
- Create: `tests/connectors/test_saxo_bank_api.py`

- [ ] **Step 1: Write the failing connector tests**

Create `tests/connectors/test_saxo_bank_api.py` with:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.saxo_bank_api import SaxoBankApiConnector


class DummyTransport(httpx.BaseTransport):
    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = self._responses.get(str(request.url))
        if payload is None:
            return httpx.Response(status_code=404, json={"error": "not found"})
        return httpx.Response(status_code=200, json=payload)


def load_fixture(name: str) -> dict:
    return json.loads(Path("tests/fixtures/saxo_bank", name).read_text())


def build_connector() -> SaxoBankApiConnector:
    responses = {
        "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me": load_fixture("accounts_page_1.json"),
        "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me?$skip=2": load_fixture("accounts_page_2.json"),
        "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-1": load_fixture("balance_acc_1.json"),
        "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-2": load_fixture("balance_acc_2.json"),
        "https://gateway.saxobank.com/sim/openapi/port/v1/positions/me": load_fixture("positions.json"),
    }
    client = httpx.Client(transport=DummyTransport(responses))
    return SaxoBankApiConnector(base_url="https://gateway.saxobank.com/sim/openapi", client=client)


def build_profile() -> AccessProfile:
    return AccessProfile(
        profile_id="nico-saxo-bank-sim",
        connector_id="saxo_bank_api",
        institution_slug="saxo-bank",
        owner_slug="nico",
    )


def build_credentials() -> RuntimeCredentials:
    return RuntimeCredentials(username="nico", access_token="token-123")


def test_saxo_connector_maps_accounts_balances_positions_and_snapshots() -> None:
    connector = build_connector()

    result = connector.fetch(build_profile(), build_credentials())

    assert [account.source_account_id for account in result.accounts] == ["acc-1", "acc-2", "acc-2"]
    assert result.accounts[0].display_name == "Main account"
    assert result.balances[0].source_account_id == "acc-1"
    assert result.balances[0].amount == "1500.25"
    assert result.positions[0].source_account_id == "acc-2"
    assert result.positions[0].asset_symbol == "SPY"
    assert result.positions[0].quantity == "12"
    assert result.snapshots[0].snapshot_name == "accounts"
    assert result.snapshots[-1].snapshot_name == "positions"
    assert result.warnings == ["Skipped unsupported position asset type: FxOption"]


def test_saxo_connector_uses_fixture_capture_time_when_source_timestamp_missing() -> None:
    connector = build_connector()

    result = connector.fetch(build_profile(), build_credentials())

    assert result.balances[0].observed_at == datetime(2026, 4, 12, 10, 0, tzinfo=UTC)


def test_saxo_connector_requires_access_token() -> None:
    connector = build_connector()

    with pytest.raises(ValueError, match="access_token is required"):
        connector.fetch(build_profile(), RuntimeCredentials(username="nico"))


def test_saxo_connector_fails_when_account_key_missing_from_balance_mapping() -> None:
    connector = SaxoBankApiConnector(
        base_url="https://gateway.saxobank.com/sim/openapi",
        client=httpx.Client(
            transport=DummyTransport(
                {
                    "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me": {
                        "Data": [{"AccountKey": "acc-1", "DisplayName": "Main account", "AccountType": "Cash", "Currency": "EUR"}]
                    },
                    "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-1": {
                        "Data": [{"CashBalance": 100}]
                    },
                    "https://gateway.saxobank.com/sim/openapi/port/v1/positions/me": {"Data": []},
                }
            )
        ),
    )

    with pytest.raises(ValueError, match="source_account_id is required"):
        connector.fetch(build_profile(), build_credentials())
```

- [ ] **Step 2: Add fixture payloads**

Create `tests/fixtures/saxo_bank/accounts_page_1.json`:

```json
{
  "__count": 3,
  "__next": "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me?$skip=2",
  "Data": [
    {
      "AccountKey": "acc-1",
      "DisplayName": "Main account",
      "AccountType": "Cash",
      "Currency": "EUR"
    },
    {
      "AccountKey": "acc-2",
      "DisplayName": "Brokerage",
      "AccountType": "Client",
      "Currency": "USD"
    }
  ]
}
```

Create `tests/fixtures/saxo_bank/accounts_page_2.json`:

```json
{
  "__count": 3,
  "Data": [
    {
      "AccountKey": "acc-3",
      "DisplayName": "Unused account",
      "AccountType": "Client",
      "Currency": "USD"
    }
  ]
}
```

Create `tests/fixtures/saxo_bank/balance_acc_1.json`:

```json
{
  "AccountKey": "acc-1",
  "Currency": "EUR",
  "CashBalance": 1500.25
}
```

Create `tests/fixtures/saxo_bank/balance_acc_2.json`:

```json
{
  "AccountKey": "acc-2",
  "Currency": "USD",
  "CashBalance": 250.75
}
```

Create `tests/fixtures/saxo_bank/positions.json`:

```json
{
  "__count": 2,
  "Data": [
    {
      "AccountKey": "acc-2",
      "AssetType": "Stock",
      "Uic": 1001,
      "Symbol": "SPY",
      "Description": "SPDR S&P 500 ETF Trust",
      "Amount": 12,
      "PriceOpen": 510.1,
      "Currency": "USD"
    },
    {
      "AccountKey": "acc-2",
      "AssetType": "FxOption",
      "Uic": 2002,
      "Symbol": "EURUSD",
      "Description": "Unsupported derivative",
      "Amount": 1,
      "PriceOpen": 1.2,
      "Currency": "USD"
    }
  ]
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_saxo_bank_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'financebuddy.connectors.saxo_bank_api'`

- [ ] **Step 4: Commit the failing test scaffolding**

```bash
git add tests/fixtures/saxo_bank tests/connectors/test_saxo_bank_api.py
git commit -m "test: add Saxo connector fixture coverage"
```

### Task 3: Implement The Saxo Connector

**Files:**
- Create: `financebuddy/connectors/saxo_bank_api.py`
- Modify: `financebuddy/connectors/__init__.py`
- Modify: `tests/connectors/test_saxo_bank_api.py`

- [ ] **Step 1: Write minimal connector implementation**

Create `financebuddy/connectors/saxo_bank_api.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)


SUPPORTED_ASSET_TYPES = {"Stock", "Etf"}


class SaxoBankApiConnector:
    connector_id = "saxo_bank_api"

    def __init__(
        self,
        base_url: str = "https://gateway.saxobank.com/sim/openapi",
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client()

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult:
        if not credentials.access_token:
            raise ValueError("access_token is required")

        captured_at = datetime.now(UTC)
        accounts_payloads = self._fetch_accounts(credentials.access_token)
        balances_payloads = [
            self._get(
                f"/port/v1/balances?AccountKey={item['AccountKey']}",
                credentials.access_token,
            )
            for item in accounts_payloads
        ]
        positions_payload = self._get("/port/v1/positions/me", credentials.access_token)

        accounts = [self._map_account(item) for item in accounts_payloads]
        balances = [self._map_balance(item, captured_at) for item in balances_payloads]
        positions, warnings = self._map_positions(positions_payload.get("Data", []), captured_at)

        snapshots = [
            RawSnapshot(snapshot_name="accounts", captured_at=captured_at, payload={"Data": accounts_payloads}),
            *[
                RawSnapshot(
                    snapshot_name=f"balances-{item['AccountKey']}",
                    captured_at=captured_at,
                    payload=item,
                )
                for item in balances_payloads
            ],
            RawSnapshot(snapshot_name="positions", captured_at=captured_at, payload=positions_payload),
        ]

        return ConnectorFetchResult(
            accounts=accounts,
            balances=balances,
            positions=positions,
            snapshots=snapshots,
            warnings=warnings,
        )

    def _fetch_accounts(self, access_token: str) -> list[dict]:
        payload = self._get("/port/v1/accounts/me", access_token)
        items = list(payload.get("Data", []))
        next_url = payload.get("__next")

        while next_url:
            next_payload = self._get_absolute(next_url, access_token)
            items.extend(next_payload.get("Data", []))
            next_url = next_payload.get("__next")

        return items

    def _get(self, path: str, access_token: str) -> dict:
        return self._get_absolute(f"{self._base_url}{path}", access_token)

    def _get_absolute(self, url: str, access_token: str) -> dict:
        response = self._client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()

    def _map_account(self, item: dict) -> AccountPayload:
        account_key = item.get("AccountKey")
        if not account_key:
            raise ValueError("source_account_id is required")
        return AccountPayload(
            source_account_id=account_key,
            display_name=item.get("DisplayName") or account_key,
            account_type=(item.get("AccountType") or "brokerage").lower(),
            currency=item["Currency"],
        )

    def _map_balance(self, item: dict, observed_at: datetime) -> BalancePayload:
        account_key = item.get("AccountKey")
        if not account_key:
            raise ValueError("source_account_id is required")
        return BalancePayload(
            source_account_id=account_key,
            amount=str(item["CashBalance"]),
            currency=item["Currency"],
            observed_at=observed_at,
        )

    def _map_positions(
        self,
        items: list[dict],
        observed_at: datetime,
    ) -> tuple[list[PositionPayload], list[str]]:
        positions: list[PositionPayload] = []
        warnings: list[str] = []

        for item in items:
            asset_type = item.get("AssetType")
            if asset_type not in SUPPORTED_ASSET_TYPES:
                warnings.append(f"Skipped unsupported position asset type: {asset_type}")
                continue

            account_key = item.get("AccountKey")
            if not account_key:
                raise ValueError("source_account_id is required")

            symbol = item.get("Symbol") or f"uic:{item['Uic']}"
            positions.append(
                PositionPayload(
                    source_account_id=account_key,
                    asset_symbol=symbol,
                    asset_name=item.get("Description") or symbol,
                    quantity=str(item["Amount"]),
                    unit_price=str(item["PriceOpen"]) if item.get("PriceOpen") is not None else None,
                    currency=item["Currency"],
                    observed_at=observed_at,
                )
            )

        return positions, warnings
```

- [ ] **Step 2: Export the connector**

If `financebuddy/connectors/__init__.py` is empty, replace it with:

```python
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.connectors.saxo_bank_api import SaxoBankApiConnector

__all__ = ["DemoBankApiConnector", "SaxoBankApiConnector"]
```

- [ ] **Step 3: Fix the incorrect test expectation for paginated accounts**

In `tests/connectors/test_saxo_bank_api.py`, change:

```python
assert [account.source_account_id for account in result.accounts] == ["acc-1", "acc-2", "acc-2"]
```

to:

```python
assert [account.source_account_id for account in result.accounts] == ["acc-1", "acc-2", "acc-3"]
```

- [ ] **Step 4: Run connector tests to verify they pass**

Run: `uv run pytest tests/connectors/test_saxo_bank_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/connectors/__init__.py financebuddy/connectors/saxo_bank_api.py tests/connectors/test_saxo_bank_api.py
git commit -m "feat: add Saxo Bank connector"
```

### Task 4: Extend The CLI For Connector Selection And Saxo Token Prompting

**Files:**
- Modify: `financebuddy/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Add these tests to `tests/test_cli.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from financebuddy.cli import app


runner = CliRunner()


def test_crawl_prompts_for_saxo_token_when_env_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)

    result = runner.invoke(
        app,
        [
            "crawl",
            "--connector",
            "saxo",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
        ],
        input="token-123\n",
    )

    assert result.exit_code == 0
    assert "Access token" in result.stdout
    assert "Accounts:" in result.stdout


def test_crawl_uses_saxo_token_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")

    result = runner.invoke(
        app,
        [
            "crawl",
            "--connector",
            "saxo",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
        ],
    )

    assert result.exit_code == 0
    assert "Access token" not in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL because the CLI does not yet support `--connector`, `--owner`, or `--fixture-dir`

- [ ] **Step 3: Implement the CLI changes**

Update `financebuddy/cli.py` to:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import typer

from financebuddy.config import load_config
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.connectors.saxo_bank_api import SaxoBankApiConnector
from financebuddy.services.crawl_runner import run_crawl
from financebuddy.services.reporting import render_summary


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.callback()
def main() -> None:
    """FinanceBuddy CLI."""


def _build_fixture_http_client(fixture_dir: Path) -> httpx.Client:
    responses = {
        "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me": json.loads((fixture_dir / "accounts_page_1.json").read_text()),
        "https://gateway.saxobank.com/sim/openapi/port/v1/accounts/me?$skip=2": json.loads((fixture_dir / "accounts_page_2.json").read_text()),
        "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-1": json.loads((fixture_dir / "balance_acc_1.json").read_text()),
        "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-2": json.loads((fixture_dir / "balance_acc_2.json").read_text()),
        "https://gateway.saxobank.com/sim/openapi/port/v1/balances?AccountKey=acc-3": {"AccountKey": "acc-3", "Currency": "USD", "CashBalance": 0},
        "https://gateway.saxobank.com/sim/openapi/port/v1/positions/me": json.loads((fixture_dir / "positions.json").read_text()),
    }

    class FixtureTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            payload = responses.get(str(request.url))
            if payload is None:
                return httpx.Response(status_code=404, json={"error": "not found"})
            return httpx.Response(status_code=200, json=payload)

    return httpx.Client(transport=FixtureTransport())


@app.command()
def crawl(
    data_dir: Path = typer.Option(..., exists=False),
    connector: str = typer.Option("demo"),
    username: str | None = typer.Option(None),
    owner: str | None = typer.Option(None),
    password: str | None = typer.Option(None, hide_input=True),
    fixture: Path | None = typer.Option(None, exists=True, dir_okay=False),
    fixture_dir: Path | None = typer.Option(None, exists=True, file_okay=False),
) -> None:
    """Run a crawl for a configured access profile."""
    config = load_config(data_dir)

    if connector == "demo":
        if fixture is None or username is None:
            raise typer.BadParameter("demo crawl requires --fixture and --username")
        if password is None:
            password = typer.prompt("Password", hide_input=True)

        profile = AccessProfile(
            profile_id=f"{username}-demo-bank",
            connector_id="demo_bank_api",
            institution_slug="demo-bank",
            owner_slug=username,
        )
        credentials = RuntimeCredentials(username=username, password=password)
        source_connector = DemoBankApiConnector.from_fixture_path(fixture)
    elif connector == "saxo":
        if fixture_dir is None or owner is None:
            raise typer.BadParameter("saxo crawl requires --fixture-dir and --owner")
        access_token = os.environ.get("SAXO_ACCESS_TOKEN")
        if not access_token:
            access_token = typer.prompt("Access token", hide_input=True)

        profile = AccessProfile(
            profile_id=f"{owner}-saxo-bank-sim",
            connector_id="saxo_bank_api",
            institution_slug="saxo-bank",
            owner_slug=owner,
        )
        credentials = RuntimeCredentials(username=owner, access_token=access_token)
        source_connector = SaxoBankApiConnector(client=_build_fixture_http_client(fixture_dir))
    else:
        raise typer.BadParameter(f"unsupported connector: {connector}")

    outcome = run_crawl(
        db_path=config.db_path,
        snapshot_dir=config.snapshot_dir,
        connector=source_connector,
        profile=profile,
        credentials=credentials,
    )
    typer.echo(
        render_summary(outcome["accounts"], outcome["balances"], outcome["positions"])
    )
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/cli.py tests/test_cli.py
git commit -m "feat: add Saxo crawl CLI path"
```

### Task 5: Add A Fixture-Backed End-To-End Saxo Smoke Test

**Files:**
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Add this test to `tests/test_smoke.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from financebuddy.cli import app


runner = CliRunner()


def test_saxo_fixture_crawl_persists_snapshots_and_projects_positions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")

    result = runner.invoke(
        app,
        [
            "crawl",
            "--connector",
            "saxo",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--fixture-dir",
            "tests/fixtures/saxo_bank",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "financebuddy.db").exists()
    snapshot_root = tmp_path / "snapshots"
    snapshot_files = list(snapshot_root.rglob("*.json"))
    assert any(path.name == "accounts.json" for path in snapshot_files)
    assert any(path.name == "positions.json" for path in snapshot_files)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py::test_saxo_fixture_crawl_persists_snapshots_and_projects_positions -v`
Expected: FAIL because the Saxo CLI path is not fully integrated yet or snapshot expectations do not yet match

- [ ] **Step 3: Adjust the implementation to satisfy the smoke test**

If the snapshot file names differ from the test expectation because of the
current snapshot naming rules, update the test to assert the actual safe
snapshot names produced by `persist_snapshots()` rather than changing snapshot
behavior. The implementation goal is to preserve the existing snapshot naming
mechanism, not replace it for Saxo.

- [ ] **Step 4: Run targeted and related tests**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: add Saxo fixture smoke coverage"
```

### Task 6: Update Documentation And Verify The Slice

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the failing documentation expectation**

Add this test to `tests/test_cli.py` if the suite already checks help text:

```python
def test_cli_help_mentions_saxo_connector() -> None:
    result = runner.invoke(app, ["crawl", "--help"])

    assert result.exit_code == 0
    assert "--connector" in result.stdout
    assert "saxo" in result.stdout
```

- [ ] **Step 2: Run the test to verify current behavior**

Run: `uv run pytest tests/test_cli.py::test_cli_help_mentions_saxo_connector -v`
Expected: FAIL until the help text reflects the new connector options

- [ ] **Step 3: Update the README and command help text**

Update `README.md` so the usage section includes both the existing demo crawl
and the new Saxo fixture-first crawl:

```md
# FinanceBuddy

Local-first finance crawler and portfolio tracker.

## Setup

```bash
uv sync --extra dev
```

## Run Demo Crawl

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector demo \
  --fixture tests/fixtures/demo_bank/accounts.json \
  --username alice
```

## Run Saxo Fixture Crawl

```bash
export SAXO_ACCESS_TOKEN=simulation-token
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --owner nico \
  --fixture-dir tests/fixtures/saxo_bank
```

If `SAXO_ACCESS_TOKEN` is not set, the CLI prompts for it interactively.

## Run Tests

```bash
uv run pytest -v
```
```

Also ensure the Typer option help for `--connector` lists `demo` and `saxo`.

- [ ] **Step 4: Run the focused docs/help tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_cli.py
git commit -m "docs: document Saxo fixture crawl"
```

## Self-Review

Spec coverage check:

- read-only Saxo connector: covered by Tasks 1 and 3
- interactive token entry plus env fallback: covered by Task 4
- fixture-first development and no live network in tests: covered by Tasks 2, 4, and 5
- accounts, cash balances, and stock/ETF positions: covered by Tasks 2 and 3
- snapshot retention and event-log-first integration: covered by Tasks 3 and 5
- deferred OAuth, transactions, and cost basis: intentionally out of scope and not implemented in this plan

Placeholder scan:

- no `TODO`, `TBD`, or deferred implementation placeholders remain in task steps

Type consistency check:

- `RuntimeCredentials(access_token=...)` is introduced before Saxo connector tasks use it
- `SaxoBankApiConnector.fetch()` returns the existing `ConnectorFetchResult`
- CLI steps use `--connector`, `--owner`, and `--fixture-dir` consistently across tests and implementation
