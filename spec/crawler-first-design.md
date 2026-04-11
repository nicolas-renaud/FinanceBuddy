# FinanceBuddy Crawler-First Design

## Scope

This document defines the first implementation slice of FinanceBuddy.

The goal of this slice is to fetch live financial data locally, normalize it, and persist it in a way that supports future replay, historical analysis, and household-aware reporting.

Included in scope:

- manual CLI-triggered crawls
- one first institution integration using an API
- interactive credential entry at runtime
- normalized local persistence
- raw snapshot retention
- event-log-first storage design
- support in the model for multiple access profiles, multiple people, shared accounts, and multiple currencies

Out of scope for this slice:

- dashboards and charts
- automated scheduling or daemon mode
- tax calculations
- full historical market-price ingestion
- scraper-based connectors, except as an architectural requirement

## Core Decisions

- Manual-only execution for the first milestone
- Credentials prompted interactively and kept in memory only
- SQLite for normalized local data
- JSON files for raw snapshots
- Event-log-first design with derived current-state projections
- Institution connectors abstract over API or scraping internals
- Future market-price ingestion kept separate from account crawling
- Base currency configurable by user, defaulting to EUR, with USD support required

## Architecture

The first phase should be implemented as an event-log-first local application with clear module boundaries.

### CLI

The CLI is the only execution entrypoint in the first milestone. It is responsible for:

- starting manual crawl runs
- prompting for credentials interactively
- selecting access profiles or institutions to crawl
- displaying a simple summary of current observed balances and positions

### Institution Connectors

Each institution connector is the code integration for one institution, such as a specific bank or broker.

Connector responsibilities:

- establish authenticated access using runtime-provided credentials
- fetch raw institution data
- expose discovered accounts, balances, positions, and source metadata
- hide whether the integration uses an API, scraping, or a hybrid strategy

The rest of the system must interact with connectors through a stable contract and remain agnostic to the fetch mechanism.

### Ingestion

The ingestion layer validates fetched data and transforms it into normalized observation events.

It should produce immutable records describing what was observed at a given time, rather than mutating current-state data directly.

### Projection

The projection layer derives current-state views from the event log.

Examples:

- latest account balance
- latest security position
- current portfolio valuation in source currency
- current portfolio valuation in the user's base currency

### Storage

Storage is split into:

- SQLite for normalized events and derived projections
- timestamped JSON files for raw snapshots and crawl diagnostics

## Domain Model

### Institution Connector

An institution connector is the implementation for one institution.

Examples:

- one bank integration
- one broker integration

It is not the same thing as a user login or an account.

### Access Profile

An access profile is one credentialed login for an institution.

Examples:

- your login at a bank
- your wife's login at the same bank

A crawl run is tied to one access profile.

### Crawl Run

A crawl run records one manual execution attempt.

It should include:

- access profile
- institution connector
- timestamps
- status
- warnings and errors
- references to raw snapshot files

Every attempt should create a crawl run record, including failures.

### Account

An account is the canonical financial account discovered from crawls.

Examples:

- checking account
- savings account
- brokerage account
- tax-advantaged investment account

Important account attributes:

- institution identity
- account type
- source currency
- optional tax wrapper label

### Owner And Ownership

Ownership is distinct from login visibility.

The system must model:

- you
- your wife
- shared ownership

Ownership should be explicit, for example:

- 100% you
- 100% wife
- 50/50 shared

This supports both household totals and per-person totals later.

### Asset

An asset represents a security or other tracked instrument.

Examples:

- stock
- ETF
- cash-like instrument

The model should allow multiple identifiers because institutions may expose inconsistent symbols or labels.

Examples of identifiers:

- ticker
- ISIN
- institution-specific code

### Observation Events

The first milestone should store immutable dated observations such as:

- cash balance observed
- security quantity observed
- source-provided valuation observed

The model should store quantities and prices separately where possible. Total value may be derived, but should not be the sole source of truth.

### Future Observation Types

The design should reserve room for later:

- price observations
- FX rate observations

These will come from independent ingestion pipelines and should not be coupled to account crawling frequency.

## Multi-Person And Shared-Account Model

The design must support multiple access profiles and shared-account deduplication from day one, even if the first implementation uses only one live profile.

This is because:

- both you and your wife may have accounts at the same institution
- both logins may see the same shared account
- visibility and ownership are not the same

The model therefore separates:

- institution connector
- access profile
- canonical account
- ownership

### Deduplication Rules

Observed accounts from different access profiles may map to the same canonical account.

For the first version:

- if the institution exposes a stable account ID, use it to merge sightings
- otherwise, do not silently merge accounts
- unresolved duplicates should remain separate until explicit matching rules or manual reconciliation are added

### Reporting Semantics

The system should be capable of supporting both:

- household view by default, where shared accounts are counted once
- per-person view, where totals are allocated by ownership share

## Connector Contract

All institution connectors should implement a common contract regardless of transport.

Inputs:

- access profile
- interactive credentials
- run context

Outputs:

- raw fetched payloads
- discovered account data
- discovered balance data
- discovered position data
- source metadata needed for account matching and quality assessment

Connectors should annotate identifier quality where helpful, for example whether an account identifier is stable and institution-issued.

## Data Flow

The first milestone flow is:

1. User runs a CLI crawl command.
2. The CLI prompts for credentials interactively.
3. The selected connector authenticates and fetches raw institution data.
4. Raw payloads are saved as JSON snapshots with run metadata.
5. The ingestion layer parses the raw payloads into normalized observation events.
6. The projection layer rebuilds or updates current-state views from the event log.
7. The CLI prints a summary of current balances and positions.

The design should support future replay:

- raw snapshots can be reparsed if a connector parser improves
- projections can be rebuilt if valuation or FX rules change

## Failure Policy

Partial success is allowed.

For example, if one crawl run can fetch some accounts successfully but fails for others:

- persist successful observations
- record warnings and failures explicitly
- avoid corrupting current-state projections

Projection updates must be atomic for the successfully parsed subset of data.

Raw snapshots should be retained for both successful and failed runs when they are useful for debugging.

## Currency And Valuation

The product must support multiple currencies from the start.

Requirements:

- each account and asset observation stores its source currency
- the user has a configurable base currency
- default base currency is EUR
- USD must be supported

For the first milestone, market price enrichment is not required, but the design must remain compatible with it.

Near-term rule:

- prefer source-provided values when available

Later:

- add independent market-price ingestion
- add FX rate ingestion
- project valuations into the user's base currency using separate pricing and FX data

## Testing Strategy

The first milestone should rely primarily on repeatable local tests.

Required test categories:

- fixture-based connector tests using recorded raw responses
- parser tests from raw payloads to normalized observation events
- projection tests rebuilding current state from event history
- CLI integration tests covering the manual crawl path without live credentials

Live institution tests should remain manual and should not be required for routine development.

## Deferred Areas

These are intentionally deferred:

- dashboards
- time-series visualizations
- market-price history ingestion
- tax computation
- automated scheduling
- manual reconciliation UX

The design should not block these later features, but the first implementation should not attempt to solve them yet.
