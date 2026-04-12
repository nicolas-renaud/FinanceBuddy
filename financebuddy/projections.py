from __future__ import annotations

from pathlib import Path

from financebuddy.db import transaction


def apply_events(db_path: Path, events: list[dict]) -> None:
    with transaction(db_path) as connection:
        for event in events:
            connection.execute(
                """
                INSERT INTO observation_events (
                    event_id,
                    run_id,
                    event_type,
                    canonical_account_key,
                    asset_key,
                    amount,
                    quantity,
                    currency,
                    observed_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["run_id"],
                    event["event_type"],
                    event["canonical_account_key"],
                    event["asset_key"],
                    event["amount"],
                    event["quantity"],
                    event["currency"],
                    event["observed_at"],
                    event["payload_json"],
                ),
            )

            if event["event_type"] == "balance_observed":
                connection.execute(
                    """
                    INSERT INTO current_balances (
                        canonical_account_key,
                        amount,
                        currency,
                        observed_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(canonical_account_key) DO UPDATE SET
                        amount = excluded.amount,
                        currency = excluded.currency,
                        observed_at = excluded.observed_at
                    """,
                    (
                        event["canonical_account_key"],
                        event["amount"],
                        event["currency"],
                        event["observed_at"],
                    ),
                )
            elif event["event_type"] == "position_observed":
                connection.execute(
                    """
                    INSERT INTO current_positions (
                        canonical_account_key,
                        asset_key,
                        quantity,
                        unit_price,
                        currency,
                        observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_account_key, asset_key) DO UPDATE SET
                        quantity = excluded.quantity,
                        unit_price = excluded.unit_price,
                        currency = excluded.currency,
                        observed_at = excluded.observed_at
                    """,
                    (
                        event["canonical_account_key"],
                        event["asset_key"],
                        event["quantity"],
                        event["amount"],
                        event["currency"],
                        event["observed_at"],
                    ),
                )
