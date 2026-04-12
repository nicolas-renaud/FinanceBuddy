from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from financebuddy.models import AccountPayload, BalancePayload, PositionPayload
from financebuddy.services.currency_conversion import CurrencyConversionService
from financebuddy.services.reporting import render_summary


def test_render_summary_groups_holdings_by_account_in_a_tree_with_base_currency_totals() -> None:
    summary = render_summary(
        accounts=[
            AccountPayload(
                source_account_id="ACC-001",
                display_name="Saxo Global Account",
                account_type="brokerage",
                currency="EUR",
            ),
            AccountPayload(
                source_account_id="ACC-002",
                display_name="Saxo Trading Account",
                account_type="brokerage",
                currency="USD",
            ),
        ],
        balances=[
            BalancePayload(
                source_account_id="ACC-001",
                amount="1250.50",
                currency="EUR",
                observed_at=datetime(2026, 4, 12, 8, 10, tzinfo=UTC),
            ),
            BalancePayload(
                source_account_id="ACC-002",
                amount="8420.00",
                currency="USD",
                observed_at=datetime(2026, 4, 12, 8, 11, tzinfo=UTC),
            ),
        ],
        positions=[
            PositionPayload(
                source_account_id="ACC-001",
                asset_symbol="NOVO-B",
                asset_name="Novo Nordisk B",
                quantity="12.5",
                unit_price="987.40",
                currency="DKK",
                observed_at=datetime(2026, 4, 12, 8, 15, tzinfo=UTC),
            ),
            PositionPayload(
                source_account_id="ACC-001",
                asset_symbol="CSPX",
                asset_name="iShares Core S&P 500 UCITS ETF",
                quantity="8",
                unit_price="512.30",
                currency="USD",
                observed_at=datetime(2026, 4, 12, 8, 15, tzinfo=UTC),
            ),
        ],
        base_currency="EUR",
    )

    assert summary == "\n".join(
        [
            "Account: Saxo Global Account (brokerage)",
            "`-- Total: 6674.93 EUR",
            "    |-- Cash: 1250.50 EUR",
            "    `-- Invested: 5424.43 EUR",
            "        |-- Position: NOVO-B qty=12.5 price=987.40 DKK value=12342.50 DKK (1653.90 EUR)",
            "        `-- Position: CSPX qty=8 price=512.30 USD value=4098.40 USD (3770.53 EUR)",
            "",
            "Account: Saxo Trading Account (brokerage)",
            "`-- Total: 7746.40 EUR",
            "    |-- Cash: 7746.40 EUR",
            "    `-- Invested: 0.00 EUR",
        ]
    )


def test_render_summary_raises_for_unsupported_foreign_currency() -> None:
    with pytest.raises(ValueError, match="Unsupported currency conversion: GBP -> EUR"):
        render_summary(
            accounts=[
                AccountPayload(
                    source_account_id="ACC-003",
                    display_name="Offshore Account",
                    account_type="brokerage",
                    currency="GBP",
                )
            ],
            balances=[
                BalancePayload(
                    source_account_id="ACC-003",
                    amount="100.00",
                    currency="GBP",
                    observed_at=datetime(2026, 4, 12, 8, 10, tzinfo=UTC),
                )
            ],
            positions=[],
            base_currency="EUR",
        )


def test_currency_conversion_service_supports_usd_and_dkk_to_eur() -> None:
    service = CurrencyConversionService(base_currency="EUR")

    assert service.convert(Decimal("10.00"), "USD") == Decimal("9.20")
    assert service.convert(Decimal("10.00"), "DKK") == Decimal("1.34")
