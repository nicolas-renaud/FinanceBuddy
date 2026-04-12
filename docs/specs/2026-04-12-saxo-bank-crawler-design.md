# Saxo Bank Crawler Design

## Scope

This document defines the first Saxo Bank connector slice for FinanceBuddy.

The goal of this slice is to add a real institution-shaped crawler that fits the
existing event-log-first runtime while remaining safe, local-first, and easy to
test with recorded fixtures.

Included in scope:

- one new `saxo_bank_api` connector
- fixture-first connector tests with recorded Saxo-style payloads
- manual CLI-triggered crawl path for Saxo
- interactive access-token entry at runtime
- optional `SAXO_ACCESS_TOKEN` environment-variable fallback
- read-only `GET` requests only
- account discovery
- per-account cash balance discovery
- stock and ETF position discovery
- raw JSON snapshot retention for every fetched response set
- normalization through the existing event pipeline

Out of scope for this slice:

- live OAuth implementation
- refresh-token persistence
- live network tests in CI
- transaction ingestion
- purchase-date ingestion
- cost-basis or margin computation
- price enrichment from external providers
- order history
- write or subscription endpoints

## Core Decisions

- Use direct HTTP requests with `httpx`, not an unofficial Saxo SDK
- Keep the existing connector contract and event-log-first flow intact
- Treat the runtime secret as a bearer token for the Saxo connector
- Prompt for the token interactively by default
- Do not accept the access token as a plain CLI flag in the first version
- Allow `SAXO_ACCESS_TOKEN` as a non-interactive fallback
- Start with Saxo simulation access tokens
- Design the profile identifier as a local composite identifier rather than the raw Saxo username
- Persist raw source payloads before normalization
- Defer transactions and cost basis to a later design slice

## Why Direct HTTP

Three approaches were considered:

1. Direct `httpx` connector
2. Wrap an unofficial Python Saxo SDK
3. Generate a typed client from the Saxo API specification

The first approach is recommended because it matches the current codebase
boundary best. FinanceBuddy already expects a thin connector that returns
normalized connector payloads plus raw snapshots. A direct connector keeps the
HTTP contract explicit, avoids introducing a maintenance dependency on an
unofficial SDK, and makes fixture-driven tests straightforward.

## CLI And Runtime Credential Flow

The first Saxo crawl should be triggered from the existing CLI entrypoint with a
Saxo-specific crawl mode or a Saxo-specific set of options on the `crawl`
command.

Runtime behavior:

- The user selects the Saxo connector path from the CLI.
- The CLI gathers a local owner label such as `nico`.
- If `SAXO_ACCESS_TOKEN` is set, the CLI may use it.
- Otherwise, the CLI prompts interactively for the access token.
- The token remains in memory only for the duration of the crawl.

The first version should not accept the token as a plain command-line flag.
Shell history and process inspection make flags the worst default for secrets.

## Access Profile Semantics

The local access profile identifier should not be the raw Saxo username.

Instead, FinanceBuddy should construct a stable local identifier that encodes
the owner, institution, and environment. This avoids collisions across
institutions and leaves room for simulation and live credentials to coexist.

Recommended shape:

- `profile_id = "<owner_slug>-saxo-bank-sim"`
- `connector_id = "saxo_bank_api"`
- `institution_slug = "saxo-bank"`
- `owner_slug = "<owner_slug>"`

The remote Saxo username, if later introduced through OAuth or richer account
metadata, should remain distinct from the FinanceBuddy local profile identity.

## Connector Responsibilities

The new `SaxoBankConnector` should continue to implement the existing
`fetch(profile, credentials) -> ConnectorFetchResult` contract.

Its responsibilities are:

- authenticate each request with `Authorization: Bearer <token>`
- fetch the minimum required Saxo portfolio data for v1
- follow pagination where Saxo responds with `__next`
- map raw API responses into FinanceBuddy account, balance, and position payloads
- preserve full raw responses as snapshots
- emit warnings for intentionally skipped rows
- fail fast on malformed or unsafe inputs

The connector should stay thin. It should not compute portfolio totals, infer
cost basis, or fetch external market data.

## Fetch Sequence

The first connector implementation should fetch data in this order:

1. Accounts
2. Balances per discovered account
3. Positions for the logged-in client

### Accounts

Use Saxo portfolio account endpoints to discover:

- stable account identifier
- account display name
- account type if available
- source currency

The stable account identifier is required because downstream ingestion and
projection semantics depend on it.

### Balances

Fetch balances per discovered account rather than relying only on a client-level
aggregate balance view. This keeps cash aligned to the correct account and fits
FinanceBuddy's account-scoped event model.

The first version should capture the source cash amount and source currency for
each account if Saxo exposes them clearly. If some account types do not expose a
usable cash figure, the connector should warn and skip rather than inventing one.

### Positions

Fetch positions for the accessible client and map only stock and ETF-like rows
that fit the current portfolio-tracker scope.

The connector may skip unsupported instruments in v1, for example derivatives or
complex products outside the current portfolio model. Those skips should produce
warnings so the crawl is transparent rather than silently incomplete.

## Data Mapping

### Accounts

FinanceBuddy `AccountPayload` should be populated from Saxo account data with:

- `source_account_id`: Saxo account key or equivalent stable account identifier
- `display_name`: Saxo account display label, falling back to the account key if needed
- `account_type`: mapped Saxo account type or a stable fallback label such as `brokerage`
- `currency`: account currency

### Balances

FinanceBuddy `BalancePayload` should be populated with:

- `source_account_id`: Saxo account key
- `amount`: the account cash or equivalent available balance amount as a string
- `currency`: balance currency
- `observed_at`: response capture time or source-provided observation timestamp

### Positions

FinanceBuddy `PositionPayload` should be populated with:

- `source_account_id`: Saxo account key associated with the position
- `asset_symbol`: preferred display symbol if cleanly provided
- `asset_name`: instrument description from Saxo
- `quantity`: position quantity as a string
- `unit_price`: source-provided price if returned and appropriate for the row
- `currency`: position or instrument currency
- `observed_at`: response capture time or source-provided observation timestamp

Ticker symbols are not always stable enough for canonical identity, but the
current projection layer still keys positions by `asset_symbol`. For this first
slice, the connector should prefer a clean symbol when present. If Saxo does not
provide a reliable symbol, the connector may derive a stable fallback identifier
from a better source identifier such as ISIN or UIC, as long as the result is a
safe deterministic string.

The first implementation may therefore produce display-oriented symbols for some
rows and fallback derived identifiers for others. A later schema improvement may
separate canonical asset identity from display symbol.

## Snapshots

Every fetch group should be preserved as raw JSON snapshots under the existing
run snapshot directory.

Recommended snapshot groups:

- `accounts`
- `balances-<account-id>`
- `positions`

Snapshot names must remain safe single path segments. If the account identifier
contains unsafe characters, it should be sanitized before becoming part of the
snapshot name.

## Error Handling

The connector should fail hard when:

- the token is missing
- Saxo returns authentication or authorization failures
- required account identifiers are missing
- responses are malformed in a way that makes normalized output unsafe

The connector should warn and continue when:

- an instrument row is outside the supported v1 scope
- optional descriptive fields are missing but a safe fallback exists
- an account cannot produce a usable cash balance but positions can still be read

This split preserves crawl safety without making the first version brittle.

## Normalization And Projection

The existing FinanceBuddy normalization and projection path should remain the
default integration route.

This means:

- the Saxo connector returns a normal `ConnectorFetchResult`
- `normalize_events()` continues emitting balance and position observation events
- `apply_events()` continues appending to `observation_events`
- `reconcile_current_positions()` continues clearing stale positions for observed accounts

No transaction events or cost-basis events are added in this slice.

## Testing Strategy

The Saxo connector must be built fixture-first.

Required tests:

- connector mapping from recorded Saxo accounts fixture
- connector mapping from recorded per-account balances fixtures
- connector mapping from recorded positions fixture
- pagination handling when Saxo returns `__next`
- warnings for skipped unsupported instruments
- hard failure on missing required account identifiers
- CLI and crawl-run integration using fixtures only

The automated test suite should not depend on live Saxo access.

Manual live validation can happen later outside Codex by pointing the connector
at Saxo simulation and supplying a real simulation token.

## Future Follow-Ups

The next Saxo-specific follow-up slices should be designed separately:

- OAuth authorization-code or PKCE flow
- refresh-token persistence for longer-term local use
- transaction and booking ingestion
- purchase-date and cost-basis support
- richer asset identity model
- external valuation and FX enrichment

These should build on the same connector boundary rather than replacing it.
