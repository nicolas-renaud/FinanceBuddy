from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RawSnapshot(BaseModel):
    snapshot_name: str
    captured_at: datetime
    payload: dict


class AccountPayload(BaseModel):
    source_account_id: str | None = None
    display_name: str
    account_type: str
    currency: str


class BalancePayload(BaseModel):
    source_account_id: str | None = None
    amount: str
    currency: str
    observed_at: datetime


class PositionPayload(BaseModel):
    source_account_id: str | None = None
    asset_symbol: str
    asset_name: str
    quantity: str
    unit_price: str | None = None
    currency: str
    observed_at: datetime


class ConnectorFetchResult(BaseModel):
    accounts: list[AccountPayload] = Field(default_factory=list)
    balances: list[BalancePayload] = Field(default_factory=list)
    positions: list[PositionPayload] = Field(default_factory=list)
    snapshots: list[RawSnapshot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
