# FinanceBuddy Agent Notes

This file is for coding agents working in this repository.

## Purpose

FinanceBuddy is a local-first finance crawler and portfolio tracker.

The current milestone supports:
- manual CLI-triggered crawls
- one fixture-backed demo institution connector
- raw snapshot persistence
- normalization into an event log
- current-state projections in SQLite
- a simple CLI summary

## Primary Flow

The main runtime path is:

1. `financebuddy/cli.py`
2. `financebuddy/services/crawl_runner.py`
3. `financebuddy/connectors/demo_bank_api.py`
4. `financebuddy/snapshots.py`
5. `financebuddy/ingestion.py`
6. `financebuddy/projections.py`
7. `financebuddy/services/reporting.py`

`crawl_runner.run_crawl()` is the main orchestration entrypoint.

## Module Map

- `financebuddy/cli.py`
  - Typer CLI entrypoint.
  - `crawl` is the main command.
  - Password should be prompted interactively if not passed.
- `financebuddy/config.py`
  - Resolves local paths such as `data_dir`, `db_path`, and `snapshot_dir`.
- `financebuddy/connectors/base.py`
  - Connector contract and runtime credential types.
- `financebuddy/connectors/demo_bank_api.py`
  - Demo connector backed by fixture JSON.
- `financebuddy/models.py`
  - Pydantic models for snapshots and connector payloads.
- `financebuddy/schema.py`
  - Creates milestone-one SQLite tables.
- `financebuddy/db.py`
  - SQLite connection helper and transaction context manager.
- `financebuddy/snapshots.py`
  - Writes raw payload snapshots under `snapshots/<run_id>/`.
- `financebuddy/ingestion.py`
  - Converts connector results into event dictionaries.
- `financebuddy/projections.py`
  - Writes event log rows and maintains current-state tables.
- `financebuddy/services/crawl_runner.py`
  - Orchestrates crawl execution and crawl-run metadata persistence.
- `financebuddy/services/reporting.py`
  - Formats CLI output from crawl results.

## Storage Model

SQLite tables:
- `crawl_runs`
- `observation_events`
- `current_balances`
- `current_positions`

Filesystem data:
- `data/financebuddy.db`
- `data/snapshots/<run_id>/*.json`

The system is event-log-first:
- source fetches are preserved as raw JSON snapshots
- normalized observations are appended to `observation_events`
- current-state tables are derived projections

## Important Invariants

- Every crawl attempt should end with a `crawl_runs` row, including failures.
- Event application and crawl-run finalization should stay transactionally consistent.
- `current_balances` and `current_positions` should not regress when older events are replayed.
- Unsupported event types must fail fast.
- Missing `source_account_id` must fail fast during ingestion.
- Brokerage positions missing from a later crawl should be cleared from `current_positions` for that observed account.
- Snapshot filenames must be safe single path segments.
- Do not reintroduce password leakage through CLI flags in docs or tests without a strong reason.

## Current CLI Contract

Main command:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --fixture tests/fixtures/demo_bank/accounts.json \
  --username alice
```

The CLI prompts for the password if it is not supplied.

The access profile is currently derived from the username:
- `profile_id = "<username>-demo-bank"`
- `owner_slug = "<username>"`

## Testing Guidance

Prefer targeted tests first, then the full suite.

Useful commands:

```bash
uv run pytest -q
uv run pytest tests/test_cli.py -v
uv run pytest tests/test_schema.py -v
uv run pytest tests/test_ingestion.py -v
uv run pytest tests/test_projections.py -v
uv run pytest tests/connectors/test_demo_bank_api.py -v
```

End-to-end smoke check:

```bash
printf 'secret\n' | uv run financebuddy crawl \
  --data-dir ./data \
  --fixture tests/fixtures/demo_bank/accounts.json \
  --username alice
```

## Known Limits

This milestone does not yet implement:
- real institution APIs
- profile/config management beyond the demo connector path
- market-price or FX ingestion
- dashboards
- scheduler/daemon mode
- ownership allocation tables
- explicit tombstone events in the event log

## When Editing

- Keep the event-log-first model intact.
- Preserve the separation between connector fetch, normalization, projection, and reporting.
- Prefer adding tests that validate behavior, not just stdout.
- If you change projection semantics, check replay behavior and missing-position handling.
- If you change crawl orchestration, verify both success and failure metadata paths.
