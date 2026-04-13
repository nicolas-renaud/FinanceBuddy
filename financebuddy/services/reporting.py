from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from financebuddy.models import AccountPayload, BalancePayload, PositionPayload
from financebuddy.services.currency_conversion import CurrencyConversionService


def render_summary(
    accounts: list[AccountPayload],
    balances: list[BalancePayload],
    positions: list[PositionPayload],
    base_currency: str = "EUR",
) -> str:
    converter = CurrencyConversionService(base_currency=base_currency)
    lines: list[str] = []
    balances_by_account: dict[str, list[BalancePayload]] = defaultdict(list)
    positions_by_account: dict[str, list[PositionPayload]] = defaultdict(list)

    for balance in balances:
        if balance.source_account_id:
            balances_by_account[balance.source_account_id].append(balance)

    for position in positions:
        if position.source_account_id:
            positions_by_account[position.source_account_id].append(position)

    for index, account in enumerate(accounts):
        if account.source_account_id is None:
            raise ValueError("Account summary requires source_account_id")

        account_balances = balances_by_account[account.source_account_id]
        account_positions = positions_by_account[account.source_account_id]
        cash_total = _sum_base_currency_balances(
            account_balances,
            converter,
        )
        invested_total = _sum_base_currency_positions(
            account_positions,
            converter,
        )
        total_value = _quantize(cash_total + invested_total)

        lines.append(f"Account: {account.display_name} ({account.account_type})")
        lines.append(f"`-- Total: {_format_decimal(total_value)} {base_currency}")
        lines.append(f"    |-- Cash: {_format_decimal(cash_total)} {base_currency}")
        if account_positions:
            lines.append(
                f"    `-- Invested: {_format_decimal(invested_total)} {base_currency}"
            )
            for position_index, position in enumerate(account_positions):
                branch = "`--" if position_index == len(account_positions) - 1 else "|--"
                lines.append(
                    f"        {branch} {_format_position_line(position, converter, base_currency)}"
                )
        else:
            lines.append(f"    `-- Invested: {_format_decimal(invested_total)} {base_currency}")

        if index < len(accounts) - 1:
            lines.append("")

    return "\n".join(lines)


def _sum_base_currency_balances(
    balances: list[BalancePayload],
    converter: CurrencyConversionService,
) -> Decimal:
    return _quantize(
        sum(
            (
                converter.convert(Decimal(balance.amount), balance.currency)
                for balance in balances
            ),
            start=Decimal("0.00"),
        )
    )


def _sum_base_currency_positions(
    positions: list[PositionPayload],
    converter: CurrencyConversionService,
) -> Decimal:
    return _quantize(
        sum(
            (
                _convert_position_value(position, converter)
                for position in positions
                if position.unit_price is not None
            ),
            start=Decimal("0.00"),
        )
    )


def _format_position_line(
    position: PositionPayload,
    converter: CurrencyConversionService,
    base_currency: str,
) -> str:
    price = position.unit_price or "n/a"
    if position.unit_price is None:
        return (
            f"Position: {position.asset_symbol} qty={position.quantity} "
            f"price={price} value=n/a"
        )

    native_value = _quantize(Decimal(position.quantity) * Decimal(position.unit_price))
    base_value = converter.convert(native_value, position.currency)
    return (
        f"Position: {position.asset_symbol} qty={position.quantity} "
        f"price={price} {position.currency} "
        f"value={_format_decimal(native_value)} {position.currency} "
        f"({_format_decimal(base_value)} {base_currency})"
    )


def _convert_position_value(
    position: PositionPayload,
    converter: CurrencyConversionService,
) -> Decimal:
    if position.unit_price is None:
        return Decimal("0.00")
    native_value = Decimal(position.quantity) * Decimal(position.unit_price)
    return converter.convert(native_value, position.currency)


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_decimal(amount: Decimal) -> str:
    normalized = f"{_quantize(amount):,.2f}"
    return normalized.replace(",", "_").replace(".", ",").replace("_", ".")
