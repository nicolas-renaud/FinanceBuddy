from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: datetime
    refresh_token_expires_at: datetime
    environment: str
    app_key_hash: str


class FileTokenStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)

    def save(self, profile_id: str, token_set: TokenSet) -> None:
        path = self._path_for_profile(profile_id)
        self._secrets_dir().mkdir(parents=True, exist_ok=True)
        self._base_dir().mkdir(parents=True, exist_ok=True)
        os.chmod(self._secrets_dir(), 0o700)
        os.chmod(self._base_dir(), 0o700)

        payload = {
            **asdict(token_set),
            "expires_at": token_set.expires_at.isoformat(),
            "refresh_token_expires_at": token_set.refresh_token_expires_at.isoformat(),
        }

        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
        finally:
            os.chmod(path, 0o600)

    def get(self, profile_id: str) -> TokenSet | None:
        path = self._path_for_profile(profile_id)
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload["token_type"],
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            refresh_token_expires_at=datetime.fromisoformat(
                payload["refresh_token_expires_at"]
            ),
            environment=payload["environment"],
            app_key_hash=payload["app_key_hash"],
        )

    def delete(self, profile_id: str) -> None:
        path = self._path_for_profile(profile_id)
        if path.exists():
            path.unlink()

    def _path_for_profile(self, profile_id: str) -> Path:
        return self._base_dir() / f"{_safe_profile_segment(profile_id)}.json"

    def _base_dir(self) -> Path:
        return self._data_dir / "secrets" / "saxo"

    def _secrets_dir(self) -> Path:
        return self._data_dir / "secrets"


def _safe_profile_segment(profile_id: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", profile_id).strip("._-")
    if segment:
        return segment
    return hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:16]
