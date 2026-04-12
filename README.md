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
  --owner <owner> \
  --fixture-dir tests/fixtures/saxo_bank
```

For the Saxo crawl, the CLI uses `SAXO_ACCESS_TOKEN` when it is set. If the
environment variable is missing or empty, the command prompts interactively for
the access token before running the crawl.

## Run Tests

```bash
uv run pytest -v
```
