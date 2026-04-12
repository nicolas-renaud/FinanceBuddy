from __future__ import annotations

import json
import uuid

from financebuddy.models import ConnectorFetchResult


def normalize_events(run_id: str, result: ConnectorFetchResult) -> list[dict]:
    events: list[dict] = []

    for balance in result.balances:
        if balance.source_account_id is None:
            raise ValueError("source_account_id is required for balance events")

        events.append(
            {
                "event_id": str(uuid.uuid4()),
                "run_id": run_id,
                "event_type": "balance_observed",
                "canonical_account_key": f"account:{balance.source_account_id}",
                "asset_key": None,
                "amount": balance.amount,
                "quantity": None,
                "currency": balance.currency,
                "observed_at": balance.observed_at.isoformat(),
                "payload_json": json.dumps(balance.model_dump(mode="json")),
            }
        )

    for position in result.positions:
        if position.source_account_id is None:
            raise ValueError("source_account_id is required for position events")

        events.append(
            {
                "event_id": str(uuid.uuid4()),
                "run_id": run_id,
                "event_type": "position_observed",
                "canonical_account_key": f"account:{position.source_account_id}",
                "asset_key": f"asset:{position.asset_symbol}",
                "amount": position.unit_price,
                "quantity": position.quantity,
                "currency": position.currency,
                "observed_at": position.observed_at.isoformat(),
                "payload_json": json.dumps(position.model_dump(mode="json")),
            }
        )

    return events
