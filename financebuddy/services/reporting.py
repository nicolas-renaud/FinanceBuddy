from __future__ import annotations

from financebuddy.models import AccountPayload, BalancePayload, PositionPayload


def render_summary(
    accounts: list[AccountPayload],
    balances: list[BalancePayload],
    positions: list[PositionPayload],
) -> str:
    lines: list[str] = []

    for account in accounts:
        lines.append(f"Account: {account.display_name} ({account.account_type})")

    for balance in balances:
        lines.append(f"Balance: {balance.amount} {balance.currency}")

    for position in positions:
        lines.append(
            f"Position: {position.asset_symbol} qty={position.quantity} price={position.unit_price or 'n/a'} {position.currency}"
        )

    return "\n".join(lines)
