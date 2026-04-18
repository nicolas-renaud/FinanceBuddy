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

Create a Saxo OpenAPI simulation app with Grant type `PKCE`, Trading enabled
`no`, and Redirect URL `http://localhost/financebuddy`. Set `SAXO_APP_KEY` in
your environment, then run:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner>
```

When no usable refresh token exists, the CLI starts an interactive login flow:
it prints and can open the authorization URL, waits for the localhost callback,
saves the refresh token under `data/secrets/saxo/`, and continues the crawl.
Later crawls refresh automatically. Use `--no-auth-login` for non-interactive
runs, or trigger login explicitly with:

```bash
uv run financebuddy saxo-auth login --data-dir ./data --owner <owner>
```

`SAXO_ACCESS_TOKEN` is still available as a short-lived development override.
Do not commit app keys, tokens, or files under `data/secrets/`.

For example, with 1Password:

```bash
op run --env-file .env.1password -- uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner>
```

## Run Tests

```bash
uv run pytest -v
```
