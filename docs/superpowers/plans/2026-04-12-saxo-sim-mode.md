# Saxo SIM Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Saxo SIM crawl mode that uses a bearer token against Saxo's simulation OpenAPI while preserving the existing fixture-backed Saxo workflow.

**Architecture:** Keep `--connector saxo` as the entrypoint and add an explicit `--saxo-source fixture|sim` option in the CLI. Reuse `SaxoBankConnector` for both fixture and SIM modes by building either a mock `httpx.Client` from fixture files or a real SIM `httpx.Client` pointed at `https://gateway.saxobank.com/sim/openapi`, and extend the connector to fetch `/me` endpoints for accounts, balances, and positions in SIM mode.

**Tech Stack:** Python, Typer, httpx, pytest

---

### Task 1: CLI source selection and validation

**Files:**
- Modify: `financebuddy/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_crawl_command_runs_saxo_connector_in_sim_mode_with_env_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAXO_ACCESS_TOKEN", "token-123")

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "sim",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_crawl_command_runs_saxo_connector_in_sim_mode_with_env_token -q`
Expected: FAIL because `--saxo-source` is not a recognized option.

- [ ] **Step 3: Write minimal implementation**

```python
def crawl(
    ...,
    saxo_source: str = typer.Option(
        "fixture",
        "--saxo-source",
        help="Saxo source to run: fixture|sim.",
    ),
) -> None:
    ...
    elif connector == "saxo":
        if owner is None:
            raise typer.BadParameter("--owner is required for the Saxo connector")
        if saxo_source == "fixture":
            if fixture_dir is None:
                raise typer.BadParameter("--fixture-dir is required for --saxo-source fixture")
            connector_impl = _build_saxo_connector_from_fixture_dir(fixture_dir)
        elif saxo_source == "sim":
            connector_impl = _build_saxo_sim_connector()
        else:
            raise typer.BadParameter(f"Unsupported Saxo source: {saxo_source}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_crawl_command_runs_saxo_connector_in_sim_mode_with_env_token -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add financebuddy/cli.py tests/test_cli.py
git commit -m "feat: add saxo sim cli mode"
```

### Task 2: Real SIM fetch behavior in the Saxo connector

**Files:**
- Modify: `financebuddy/connectors/saxo_bank_api.py`
- Test: `tests/connectors/test_saxo_bank_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_connector_fetches_sim_me_endpoints() -> None:
    connector = build_connector(
        {
            ("GET", "/port/v1/accounts/me"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC-001", "Name": "Primary", "AccountType": "Normal", "Currency": "EUR"}]},
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/balances/me"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC-001", "CashBalance": "1250.50", "Currency": "EUR", "LastUpdated": "2026-04-12T08:10:00Z"}]},
                headers={"content-type": "application/json"},
            ),
            ("GET", "/port/v1/positions/me"): httpx.Response(
                200,
                json={"Data": [{"AccountKey": "ACC-001", "Symbol": "NOVO-B", "Description": "Novo Nordisk B", "Quantity": "12.5", "Price": "987.40", "Currency": "DKK", "LastUpdated": "2026-04-12T08:15:00Z"}]},
                headers={"content-type": "application/json"},
            ),
        }
    )

    result = connector.fetch(build_profile(), build_credentials())

    assert [account.source_account_id for account in result.accounts] == ["ACC-001"]
    assert [balance.source_account_id for balance in result.balances] == ["ACC-001"]
    assert [position.source_account_id for position in result.positions] == ["ACC-001"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_saxo_bank_api.py::test_connector_fetches_sim_me_endpoints -q`
Expected: FAIL because the connector currently requests `/port/v1/accounts` and per-account balance endpoints instead of `/me` endpoints.

- [ ] **Step 3: Write minimal implementation**

```python
def fetch(...):
    ...
    accounts_payload, account_snapshots = self._fetch_accounts(headers)
    ...
    balances_payload, balances_snapshot = self._fetch_balances(headers)
    ...
    positions_payload, positions_snapshot = self._fetch_positions(headers)

def _fetch_accounts(self, headers: dict[str, str]) -> tuple[list[dict[str, Any]], list[RawSnapshot]]:
    if self._base_url.endswith("/sim/openapi"):
        payload = self._request_json("/port/v1/accounts/me", headers)
        ...
    return self._fetch_account_pages(headers)

def _fetch_balances(self, headers: dict[str, str]) -> tuple[list[dict[str, Any]], RawSnapshot]:
    if self._base_url.endswith("/sim/openapi"):
        payload = self._request_json("/port/v1/balances/me", headers)
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/connectors/test_saxo_bank_api.py::test_connector_fetches_sim_me_endpoints -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add financebuddy/connectors/saxo_bank_api.py tests/connectors/test_saxo_bank_api.py
git commit -m "feat: fetch real Saxo sim account data"
```

### Task 3: End-to-end CLI coverage for fixture and SIM modes

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_smoke.py`
- Modify: `financebuddy/cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_crawl_command_requires_fixture_dir_for_saxo_fixture_mode(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "fixture",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code != 0
    assert "--fixture-dir is required for --saxo-source fixture" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_crawl_command_requires_fixture_dir_for_saxo_fixture_mode -q`
Expected: FAIL because the current validation does not mention `--saxo-source fixture`.

- [ ] **Step 3: Write minimal implementation**

```python
elif connector == "saxo":
    ...
    if saxo_source == "fixture":
        if fixture_dir is None:
            raise typer.BadParameter("--fixture-dir is required for --saxo-source fixture")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_crawl_command_requires_fixture_dir_for_saxo_fixture_mode -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add financebuddy/cli.py tests/test_cli.py tests/test_smoke.py
git commit -m "test: cover saxo fixture and sim cli modes"
```

### Task 4: Final verification

**Files:**
- Modify: `financebuddy/cli.py`
- Modify: `financebuddy/connectors/saxo_bank_api.py`
- Modify: `tests/connectors/test_saxo_bank_api.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Run targeted verification**

Run: `uv run pytest tests/connectors/test_saxo_bank_api.py tests/test_cli.py tests/test_smoke.py -q`
Expected: PASS with all Saxo connector and CLI tests green.

- [ ] **Step 2: Run full verification**

Run: `uv run pytest -q`
Expected: PASS with the full suite green.

- [ ] **Step 3: Commit**

```bash
git add financebuddy/cli.py financebuddy/connectors/saxo_bank_api.py tests/connectors/test_saxo_bank_api.py tests/test_cli.py tests/test_smoke.py
git commit -m "feat: support real Saxo sim crawls"
```
