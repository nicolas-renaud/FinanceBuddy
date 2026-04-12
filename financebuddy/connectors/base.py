from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from financebuddy.models import ConnectorFetchResult


@dataclass(frozen=True)
class AccessProfile:
    profile_id: str
    connector_id: str
    institution_slug: str
    owner_slug: str


@dataclass(frozen=True)
class RuntimeCredentials:
    username: str
    password: str = field(repr=False)


class Connector(Protocol):
    connector_id: str

    def fetch(
        self,
        profile: AccessProfile,
        credentials: RuntimeCredentials,
    ) -> ConnectorFetchResult: ...
