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
