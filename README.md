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
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source fixture \
  --owner <owner> \
  --fixture-dir tests/fixtures/saxo_bank
```

## Run Saxo SIM Crawl

```bash
export SAXO_ACCESS_TOKEN=simulation-token

uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner>
```

For Saxo crawls, the CLI uses `SAXO_ACCESS_TOKEN` when it is set. If the
environment variable is missing or empty, the command prompts interactively for
the access token before running the crawl.

## Run Tests

```bash
uv run pytest -v
```
