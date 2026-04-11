# FinanceBuddy Product Intent

## Purpose

FinanceBuddy is a local-first personal finance application for monitoring the evolution of bank accounts and investment holdings over time.

The product is intended to help a household understand:

- total cash across multiple bank accounts
- stock and ETF holdings, including quantity and market value
- portfolio allocation by asset type, region, and other dimensions
- future tax implications depending on account wrappers and tax rules

## Product Principles

- Local-first: financial data is stored locally, not delegated to third-party aggregators.
- User-controlled access: credentials are provided directly by the user to local crawlers and are not handed to external services.
- Connector transparency: the rest of the system should not care whether an institution is accessed via API or scraping.
- Historical correctness: observations should be stored in a way that supports later reconstruction of historical state.
- Household-aware modeling: the system must support multiple people, separate ownership, and shared accounts without double counting.

## Long-Term Scope

FinanceBuddy is expected to evolve in stages.

### Stage 1: Crawler First

Build local connectors that fetch live data from institutions.

Initial focus:

- connect to one institution that provides an API
- fetch live balances and live positions
- store normalized current data locally
- retain raw snapshots for debugging and future replay

Explicit non-goals for the first stage:

- dashboards
- historical charting
- tax computation
- automated scheduling

### Stage 2: Dashboarding

Add visual dashboards for:

- total cash over time
- total investment value over time
- asset allocation and repartition views
- household and per-person perspectives

### Stage 3: Historical Market Data

Add independent ingestion of:

- daily stock and ETF closing prices
- FX rates for base-currency conversion

This price history pipeline is intentionally separate from account crawling because account crawls may run infrequently while price data should be collected regularly for historical charts.

### Stage 4: Tax Modeling

Add account-type-aware tax logic, including:

- tax-exempt or tax-advantaged wrappers
- taxable gains
- institution- or country-specific edge cases

The exact rules will be defined later, but the data model should preserve enough context to support them.

## Functional Intent

At maturity, the product should support:

- multiple institutions
- multiple access methods per institution family when needed
- multiple people in the same household
- shared accounts visible from more than one login
- multiple currencies
- a user-configurable base currency, defaulting to EUR and supporting USD

## Near-Term Direction

The immediate objective is to define and build the crawler foundation first, because all later historical, dashboard, and tax features depend on accurate local acquisition and normalization of financial data.
