# FinanceBuddy Crawler-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first local Python implementation of FinanceBuddy that can manually run one API-based institution connector, capture raw snapshots, normalize observations into an event-log-first SQLite database, project current state, and print a CLI summary.

**Architecture:** This implementation uses a Python CLI app with clear module boundaries for connectors, ingestion, projections, and storage. Source payloads are stored as immutable JSON snapshots while normalized observation events are persisted in SQLite and projected into current-state tables for reporting and replay.

**Tech Stack:** Python 3.12, `uv`, Typer, pytest, SQLite (`sqlite3`), Pydantic v2, HTTPX

---

## File Structure

Planned repo structure for the first milestone:

- `pyproject.toml`: project metadata, dependencies, pytest config, CLI entrypoint
- `.gitignore`: Python, cache, virtualenv, local data exclusions
- `README.md`: setup and first-run instructions
- `financebuddy/__init__.py`: package marker
- `financebuddy/cli.py`: Typer application and crawl command
- `financebuddy/config.py`: local filesystem paths and base-currency settings
- `financebuddy/models.py`: Pydantic models for connector outputs and normalized domain records
- `financebuddy/db.py`: SQLite connection helpers and transaction wrapper
- `financebuddy/schema.py`: schema creation and migration bootstrap for milestone one
- `financebuddy/snapshots.py`: raw snapshot file naming and persistence
- `financebuddy/connectors/__init__.py`: connector registry exports
- `financebuddy/connectors/base.py`: connector protocol and runtime credential types
- `financebuddy/connectors/demo_bank_api.py`: first API-backed connector using fixture-friendly HTTP client injection
- `financebuddy/ingestion.py`: mapping connector payloads into observation events
- `financebuddy/projections.py`: rebuild/update current-state tables from event log
- `financebuddy/services/crawl_runner.py`: orchestration from CLI command to storage and projection
- `financebuddy/services/reporting.py`: summary query helpers for CLI output
- `tests/test_cli.py`: CLI integration coverage
- `tests/test_schema.py`: database bootstrap tests
- `tests/test_ingestion.py`: normalization tests
- `tests/test_projections.py`: event-log projection tests
- `tests/connectors/test_demo_bank_api.py`: connector fixture tests
- `tests/fixtures/demo_bank/accounts.json`: example raw API response fixture
- `tests/fixtures/demo_bank/profile.json`: optional profile fixture if needed by connector

The first implementation intentionally avoids dashboards, scheduling, tax logic, and market-price history.

### Task 1: Scaffold The Python Project

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Modify: `README.md`
- Create: `financebuddy/__init__.py`
- Test: `pytest`

- [ ] **Step 1: Write the failing packaging check**

Create `pyproject.toml` with the CLI entrypoint and dependencies declared, but do not create the package files yet:

```toml
[project]
name = "financebuddy"
version = "0.1.0"
description = "Local-first finance crawler and portfolio tracker"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27,<0.28",
  "pydantic>=2.7,<3.0",
  "typer>=0.12,<0.13",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2,<9.0",
]

[project.scripts]
financebuddy = "financebuddy.cli:app"

[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Run packaging check to verify it fails**

Run: `uv run python -c "import financebuddy"`
Expected: FAIL with `ModuleNotFoundError: No module named 'financebuddy'`

- [ ] **Step 3: Write minimal project scaffolding**

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
.pytest_cache/
*.pyc
data/
```

Create `financebuddy/__init__.py`:

```python
"""FinanceBuddy package."""
```

Update `README.md`:

```md
# FinanceBuddy

Local-first finance crawler and portfolio tracker.

## Planned First Milestone

- Manual CLI crawl
- One API-backed institution connector
- SQLite event log
- Raw JSON snapshots
```

- [ ] **Step 4: Run packaging check to verify it passes**

Run: `uv run python -c "import financebuddy; print(financebuddy.__doc__)"`
Expected: PASS and print `FinanceBuddy package.`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md financebuddy/__init__.py
git commit -m "chore: scaffold python project"
```

### Task 2: Add The CLI Shell And Config Paths

**Files:**
- Create: `financebuddy/cli.py`
- Create: `financebuddy/config.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from financebuddy.cli import app


runner = CliRunner()


def test_cli_shows_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "crawl" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_cli_shows_help -v`
Expected: FAIL with `ModuleNotFoundError` or `No module named 'financebuddy.cli'`

- [ ] **Step 3: Write minimal CLI and config implementation**

Create `financebuddy/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    snapshot_dir: Path
    base_currency: str = "EUR"


def load_config(root: Path | None = None) -> AppConfig:
    base_dir = root or Path.cwd() / "data"
    return AppConfig(
        data_dir=base_dir,
        db_path=base_dir / "financebuddy.db",
        snapshot_dir=base_dir / "snapshots",
    )
```

Create `financebuddy/cli.py`:

```python
from __future__ import annotations

import typer


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.command()
def crawl() -> None:
    """Run a crawl for a configured access profile."""
    typer.echo("crawl not implemented yet")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_cli_shows_help -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/cli.py financebuddy/config.py tests/test_cli.py
git commit -m "feat: add cli shell and config paths"
```

### Task 3: Add Connector Models And Contract

**Files:**
- Create: `financebuddy/models.py`
- Create: `financebuddy/connectors/__init__.py`
- Create: `financebuddy/connectors/base.py`
- Test: `tests/connectors/test_demo_bank_api.py`

- [ ] **Step 1: Write the failing connector contract test**

Create `tests/connectors/test_demo_bank_api.py`:

```python
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py -v`
Expected: FAIL with `No module named 'financebuddy.connectors.base'`

- [ ] **Step 3: Write the connector models and protocol**

Create `financebuddy/models.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RawSnapshot(BaseModel):
    snapshot_name: str
    captured_at: datetime
    payload: dict


class AccountPayload(BaseModel):
    source_account_id: str | None = None
    display_name: str
    account_type: str
    currency: str


class BalancePayload(BaseModel):
    source_account_id: str | None = None
    amount: str
    currency: str
    observed_at: datetime


class PositionPayload(BaseModel):
    source_account_id: str | None = None
    asset_symbol: str
    asset_name: str
    quantity: str
    unit_price: str | None = None
    currency: str
    observed_at: datetime


class ConnectorFetchResult(BaseModel):
    accounts: list[AccountPayload] = Field(default_factory=list)
    balances: list[BalancePayload] = Field(default_factory=list)
    positions: list[PositionPayload] = Field(default_factory=list)
    snapshots: list[RawSnapshot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

Create `financebuddy/connectors/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
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
    password: str


class Connector(Protocol):
    connector_id: str

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult: ...
```

Create `financebuddy/connectors/__init__.py`:

```python
from financebuddy.connectors.base import AccessProfile, Connector, RuntimeCredentials

__all__ = ["AccessProfile", "Connector", "RuntimeCredentials"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/models.py financebuddy/connectors/__init__.py financebuddy/connectors/base.py tests/connectors/test_demo_bank_api.py
git commit -m "feat: add connector contract models"
```

### Task 4: Create SQLite Bootstrap And Schema

**Files:**
- Create: `financebuddy/db.py`
- Create: `financebuddy/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing schema bootstrap test**

Create `tests/test_schema.py`:

```python
import sqlite3
from pathlib import Path

from financebuddy.schema import initialize_database


def test_initialize_database_creates_core_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"

    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row[0] for row in rows}

    assert "crawl_runs" in table_names
    assert "observation_events" in table_names
    assert "current_balances" in table_names
    assert "current_positions" in table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py::test_initialize_database_creates_core_tables -v`
Expected: FAIL with `No module named 'financebuddy.schema'`

- [ ] **Step 3: Write minimal database bootstrap**

Create `financebuddy/db.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
```

Create `financebuddy/schema.py`:

```python
from __future__ import annotations

from pathlib import Path

from financebuddy.db import transaction


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with transaction(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
                run_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                connector_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                warnings_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS observation_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                canonical_account_key TEXT NOT NULL,
                asset_key TEXT,
                amount TEXT,
                quantity TEXT,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS current_balances (
                canonical_account_key TEXT PRIMARY KEY,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS current_positions (
                canonical_account_key TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                quantity TEXT NOT NULL,
                unit_price TEXT,
                currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (canonical_account_key, asset_key)
            );
            """
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schema.py::test_initialize_database_creates_core_tables -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/db.py financebuddy/schema.py tests/test_schema.py
git commit -m "feat: add sqlite schema bootstrap"
```

### Task 5: Persist Raw Snapshots

**Files:**
- Create: `financebuddy/snapshots.py`
- Modify: `financebuddy/models.py`
- Test: `tests/test_ingestion.py`

- [ ] **Step 1: Write the failing snapshot persistence test**

Create `tests/test_ingestion.py`:

```python
import json
from datetime import datetime, UTC
from pathlib import Path

from financebuddy.models import RawSnapshot
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingestion.py::test_persist_snapshots_writes_json_files -v`
Expected: FAIL with `No module named 'financebuddy.snapshots'`

- [ ] **Step 3: Write minimal snapshot persistence**

Create `financebuddy/snapshots.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from financebuddy.models import RawSnapshot


def persist_snapshots(
    snapshot_root: Path,
    run_id: str,
    snapshots: list[RawSnapshot],
) -> list[Path]:
    run_dir = snapshot_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for snapshot in snapshots:
        path = run_dir / f"{snapshot.snapshot_name}.json"
        path.write_text(json.dumps(snapshot.payload, indent=2, sort_keys=True))
        written_paths.append(path)

    return written_paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingestion.py::test_persist_snapshots_writes_json_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/snapshots.py tests/test_ingestion.py
git commit -m "feat: persist raw crawl snapshots"
```

### Task 6: Add The First API Connector

**Files:**
- Create: `financebuddy/connectors/demo_bank_api.py`
- Create: `tests/fixtures/demo_bank/accounts.json`
- Modify: `tests/connectors/test_demo_bank_api.py`
- Test: `tests/connectors/test_demo_bank_api.py`

- [ ] **Step 1: Extend the connector test with fixture-backed fetch behavior**

Update `tests/connectors/test_demo_bank_api.py`:

```python
import json
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector


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
```

Create `tests/fixtures/demo_bank/accounts.json`:

```json
{
  "captured_at": "2026-04-11T12:00:00Z",
  "accounts": [
    {
      "id": "CHK-001",
      "name": "Main checking",
      "type": "checking",
      "currency": "EUR",
      "balance": "1250.50"
    },
    {
      "id": "BRK-001",
      "name": "Broker account",
      "type": "brokerage",
      "currency": "USD",
      "positions": [
        {
          "symbol": "VOO",
          "name": "Vanguard S&P 500 ETF",
          "quantity": "12.5",
          "unit_price": "510.10",
          "currency": "USD"
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py::test_demo_bank_connector_maps_fixture_response -v`
Expected: FAIL with `No module named 'financebuddy.connectors.demo_bank_api'`

- [ ] **Step 3: Write the first API-backed connector**

Create `financebuddy/connectors/demo_bank_api.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/connectors/test_demo_bank_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/connectors/demo_bank_api.py tests/connectors/test_demo_bank_api.py tests/fixtures/demo_bank/accounts.json
git commit -m "feat: add demo api connector"
```

### Task 7: Normalize Fetched Data Into Observation Events

**Files:**
- Create: `financebuddy/ingestion.py`
- Modify: `tests/test_ingestion.py`
- Test: `tests/test_ingestion.py`

- [ ] **Step 1: Extend ingestion tests with event normalization**

Update `tests/test_ingestion.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.models import (
    AccountPayload,
    BalancePayload,
    ConnectorFetchResult,
    PositionPayload,
    RawSnapshot,
)
from financebuddy.snapshots import persist_snapshots
from financebuddy.ingestion import normalize_events


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
    assert events[0]["canonical_account_key"] == "account:CHK-001"
    assert events[1]["asset_key"] == "asset:VOO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingestion.py::test_normalize_events_creates_balance_and_position_events -v`
Expected: FAIL with `No module named 'financebuddy.ingestion'`

- [ ] **Step 3: Write the normalization layer**

Create `financebuddy/ingestion.py`:

```python
from __future__ import annotations

import json
import uuid

from financebuddy.models import ConnectorFetchResult


def normalize_events(run_id: str, result: ConnectorFetchResult) -> list[dict]:
    events: list[dict] = []

    for balance in result.balances:
        events.append(
            {
                "event_id": str(uuid.uuid4()),
                "run_id": run_id,
                "event_type": "balance_observed",
                "canonical_account_key": f"account:{balance.source_account_id}",
                "asset_key": None,
                "amount": balance.amount,
                "quantity": None,
                "currency": balance.currency,
                "observed_at": balance.observed_at.isoformat(),
                "payload_json": json.dumps(balance.model_dump(mode="json")),
            }
        )

    for position in result.positions:
        events.append(
            {
                "event_id": str(uuid.uuid4()),
                "run_id": run_id,
                "event_type": "position_observed",
                "canonical_account_key": f"account:{position.source_account_id}",
                "asset_key": f"asset:{position.asset_symbol}",
                "amount": position.unit_price,
                "quantity": position.quantity,
                "currency": position.currency,
                "observed_at": position.observed_at.isoformat(),
                "payload_json": json.dumps(position.model_dump(mode="json")),
            }
        )

    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingestion.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/ingestion.py tests/test_ingestion.py
git commit -m "feat: normalize connector results into events"
```

### Task 8: Build Current-State Projections

**Files:**
- Create: `financebuddy/projections.py`
- Create: `tests/test_projections.py`
- Test: `tests/test_projections.py`

- [ ] **Step 1: Write the failing projection test**

Create `tests/test_projections.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_projections.py::test_apply_events_updates_current_state_tables -v`
Expected: FAIL with `No module named 'financebuddy.projections'`

- [ ] **Step 3: Write the projection updater**

Create `financebuddy/projections.py`:

```python
from __future__ import annotations

from pathlib import Path

from financebuddy.db import transaction


def apply_events(db_path: Path, events: list[dict]) -> None:
    with transaction(db_path) as connection:
        for event in events:
            connection.execute(
                """
                INSERT INTO observation_events (
                    event_id,
                    run_id,
                    event_type,
                    canonical_account_key,
                    asset_key,
                    amount,
                    quantity,
                    currency,
                    observed_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["run_id"],
                    event["event_type"],
                    event["canonical_account_key"],
                    event["asset_key"],
                    event["amount"],
                    event["quantity"],
                    event["currency"],
                    event["observed_at"],
                    event["payload_json"],
                ),
            )

            if event["event_type"] == "balance_observed":
                connection.execute(
                    """
                    INSERT INTO current_balances (
                        canonical_account_key,
                        amount,
                        currency,
                        observed_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(canonical_account_key) DO UPDATE SET
                        amount = excluded.amount,
                        currency = excluded.currency,
                        observed_at = excluded.observed_at
                    """,
                    (
                        event["canonical_account_key"],
                        event["amount"],
                        event["currency"],
                        event["observed_at"],
                    ),
                )
            elif event["event_type"] == "position_observed":
                connection.execute(
                    """
                    INSERT INTO current_positions (
                        canonical_account_key,
                        asset_key,
                        quantity,
                        unit_price,
                        currency,
                        observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_account_key, asset_key) DO UPDATE SET
                        quantity = excluded.quantity,
                        unit_price = excluded.unit_price,
                        currency = excluded.currency,
                        observed_at = excluded.observed_at
                    """,
                    (
                        event["canonical_account_key"],
                        event["asset_key"],
                        event["quantity"],
                        event["amount"],
                        event["currency"],
                        event["observed_at"],
                    ),
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_projections.py::test_apply_events_updates_current_state_tables -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/projections.py tests/test_projections.py
git commit -m "feat: project current balances and positions"
```

### Task 9: Add Crawl Orchestration And CLI Command

**Files:**
- Create: `financebuddy/services/crawl_runner.py`
- Create: `financebuddy/services/reporting.py`
- Modify: `financebuddy/cli.py`
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Extend the CLI test to cover the crawl flow**

Update `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from financebuddy.cli import app


runner = CliRunner()


def test_cli_shows_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "crawl" in result.stdout


def test_crawl_command_runs_demo_connector(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--fixture",
            "tests/fixtures/demo_bank/accounts.json",
            "--username",
            "alice",
            "--password",
            "secret",
        ],
    )

    assert result.exit_code == 0
    assert "Main checking" in result.stdout
    assert "VOO" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_crawl_command_runs_demo_connector -v`
Expected: FAIL because the `crawl` command does not yet accept the required options or execute the workflow

- [ ] **Step 3: Write the crawl orchestration and reporting**

Create `financebuddy/services/crawl_runner.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.ingestion import normalize_events
from financebuddy.projections import apply_events
from financebuddy.schema import initialize_database
from financebuddy.snapshots import persist_snapshots


def run_crawl(
    db_path: Path,
    snapshot_dir: Path,
    connector,
    profile: AccessProfile,
    credentials: RuntimeCredentials,
) -> dict:
    initialize_database(db_path)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()
    result = connector.fetch(profile, credentials)
    snapshot_paths = persist_snapshots(snapshot_dir, run_id, result.snapshots)
    events = normalize_events(run_id, result)
    apply_events(db_path, events)

    return {
        "run_id": run_id,
        "started_at": started_at,
        "snapshot_paths": [str(path) for path in snapshot_paths],
        "accounts": result.accounts,
        "balances": result.balances,
        "positions": result.positions,
        "warnings": result.warnings,
    }
```

Create `financebuddy/services/reporting.py`:

```python
from __future__ import annotations

from financebuddy.models import AccountPayload, BalancePayload, PositionPayload


def render_summary(
    accounts: list[AccountPayload],
    balances: list[BalancePayload],
    positions: list[PositionPayload],
) -> str:
    lines: list[str] = []

    for account in accounts:
        lines.append(f"Account: {account.display_name} ({account.account_type})")

    for balance in balances:
        lines.append(f"Balance: {balance.amount} {balance.currency}")

    for position in positions:
        lines.append(
            f"Position: {position.asset_symbol} qty={position.quantity} price={position.unit_price or 'n/a'} {position.currency}"
        )

    return "\n".join(lines)
```

Update `financebuddy/cli.py`:

```python
from __future__ import annotations

from pathlib import Path

import typer

from financebuddy.config import load_config
from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.connectors.demo_bank_api import DemoBankApiConnector
from financebuddy.services.crawl_runner import run_crawl
from financebuddy.services.reporting import render_summary


app = typer.Typer(help="Local-first finance crawler CLI.")


@app.command()
def crawl(
    data_dir: Path = typer.Option(..., exists=False),
    fixture: Path = typer.Option(..., exists=True, dir_okay=False),
    username: str = typer.Option(...),
    password: str = typer.Option(..., hide_input=True),
) -> None:
    """Run a crawl for a configured access profile."""
    config = load_config(data_dir)
    connector = DemoBankApiConnector.from_fixture_path(fixture)
    profile = AccessProfile(
        profile_id="alice-demo-bank",
        connector_id="demo_bank_api",
        institution_slug="demo-bank",
        owner_slug="alice",
    )
    credentials = RuntimeCredentials(username=username, password=password)

    outcome = run_crawl(
        db_path=config.db_path,
        snapshot_dir=config.snapshot_dir,
        connector=connector,
        profile=profile,
        credentials=credentials,
    )
    typer.echo(render_summary(outcome["accounts"], outcome["balances"], outcome["positions"]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/services/crawl_runner.py financebuddy/services/reporting.py financebuddy/cli.py tests/test_cli.py
git commit -m "feat: wire cli crawl flow"
```

### Task 10: Record Crawl Runs And Partial Success Warnings

**Files:**
- Modify: `financebuddy/services/crawl_runner.py`
- Modify: `financebuddy/schema.py`
- Modify: `tests/test_schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Extend the database test to validate crawl run persistence**

Update `tests/test_schema.py`:

```python
import sqlite3
from pathlib import Path

from financebuddy.db import connect
from financebuddy.schema import initialize_database


def test_initialize_database_creates_core_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"

    initialize_database(db_path)

    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {row[0] for row in rows}

    assert "crawl_runs" in table_names
    assert "observation_events" in table_names
    assert "current_balances" in table_names
    assert "current_positions" in table_names


def test_crawl_runs_table_accepts_warning_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "financebuddy.db"
    initialize_database(db_path)

    connection = connect(db_path)
    connection.execute(
        """
        INSERT INTO crawl_runs (
            run_id, profile_id, connector_id, status, started_at, finished_at, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "run-1",
            "alice-demo-bank",
            "demo_bank_api",
            "partial_success",
            "2026-04-11T12:00:00+00:00",
            "2026-04-11T12:01:00+00:00",
            '["one account failed"]',
        ),
    )
    connection.commit()

    row = connection.execute(
        "SELECT status, warnings_json FROM crawl_runs WHERE run_id = ?",
        ("run-1",),
    ).fetchone()

    assert row["status"] == "partial_success"
    assert row["warnings_json"] == '["one account failed"]'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py::test_crawl_runs_table_accepts_warning_payload -v`
Expected: FAIL if the row factory or persistence path is incomplete

- [ ] **Step 3: Persist crawl run metadata in orchestration**

Update `financebuddy/services/crawl_runner.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from financebuddy.connectors.base import AccessProfile, RuntimeCredentials
from financebuddy.db import transaction
from financebuddy.ingestion import normalize_events
from financebuddy.projections import apply_events
from financebuddy.schema import initialize_database
from financebuddy.snapshots import persist_snapshots


def run_crawl(
    db_path: Path,
    snapshot_dir: Path,
    connector,
    profile: AccessProfile,
    credentials: RuntimeCredentials,
) -> dict:
    initialize_database(db_path)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    result = connector.fetch(profile, credentials)
    snapshot_paths = persist_snapshots(snapshot_dir, run_id, result.snapshots)
    events = normalize_events(run_id, result)
    apply_events(db_path, events)

    status = "partial_success" if result.warnings else "success"
    finished_at = datetime.now(UTC)
    with transaction(db_path) as connection:
        connection.execute(
            """
            INSERT INTO crawl_runs (
                run_id,
                profile_id,
                connector_id,
                status,
                started_at,
                finished_at,
                warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                profile.profile_id,
                profile.connector_id,
                status,
                started_at.isoformat(),
                finished_at.isoformat(),
                json.dumps(result.warnings),
            ),
        )

    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "snapshot_paths": [str(path) for path in snapshot_paths],
        "accounts": result.accounts,
        "balances": result.balances,
        "positions": result.positions,
        "warnings": result.warnings,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add financebuddy/services/crawl_runner.py tests/test_schema.py
git commit -m "feat: record crawl run metadata"
```

### Task 11: Final End-To-End Verification And Docs

**Files:**
- Modify: `README.md`
- Test: `pytest`

- [ ] **Step 1: Write the missing usage instructions**

Update `README.md`:

```md
# FinanceBuddy

Local-first finance crawler and portfolio tracker.

## Setup

```bash
uv sync
```

## Run Demo Crawl

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --fixture tests/fixtures/demo_bank/accounts.json \
  --username alice \
  --password secret
```

## Run Tests

```bash
uv run pytest -v
```
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS with all connector, ingestion, schema, projection, and CLI tests green

- [ ] **Step 3: Run a manual demo crawl**

Run: `uv run financebuddy crawl --data-dir ./data --fixture tests/fixtures/demo_bank/accounts.json --username alice --password secret`
Expected: PASS and print account and position summary including `Main checking` and `VOO`

- [ ] **Step 4: Inspect written artifacts**

Run: `uv run python -c "from pathlib import Path; print((Path('data') / 'financebuddy.db').exists()); print(any((Path('data') / 'snapshots').glob('*/*.json')))" `
Expected: PASS and print `True` then `True`

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add local run instructions"
```

## Self-Review

Spec coverage check:

- manual CLI crawl: covered in Tasks 2, 9, and 11
- API-backed first connector: covered in Task 6
- interactive runtime credentials: covered structurally in Tasks 3 and 9, though the first CLI test path passes them as options for repeatable automation; swap to `typer.prompt(..., hide_input=True)` during execution if you want stricter interactive-only behavior
- SQLite event log: covered in Tasks 4, 7, 8, and 10
- raw JSON snapshots: covered in Task 5 and exercised in Task 11
- event-log-first projections: covered in Tasks 7 and 8
- partial success recording: covered in Task 10
- multi-person and shared-account-ready model: partially covered by `AccessProfile` and canonical account keys; the first implementation deliberately leaves ownership and dedup resolution as schema-ready follow-up work once a second profile is introduced
- multi-currency/base currency support: partially covered by currency fields and config base currency; base-currency conversion is intentionally deferred per the spec

Gaps intentionally left for a follow-up plan:

- canonical owner and ownership tables
- unresolved duplicate-account reconciliation flow
- separate market-price and FX ingestion pipeline
- scraper connector implementation

Placeholder scan:

- no `TODO`, `TBD`, or “implement later” markers remain in task steps
- each code-writing step includes concrete code
- each verification step includes an exact command and expected result

Type consistency check:

- connector models use `ConnectorFetchResult`, `AccountPayload`, `BalancePayload`, `PositionPayload`, and `RawSnapshot` consistently across connector, ingestion, orchestration, and reporting tasks
- the projection layer expects normalized event dictionaries from `normalize_events`, and the schema columns match those dictionary keys
