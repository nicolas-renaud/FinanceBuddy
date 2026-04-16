from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta

from financebuddy.auth.token_store import FileTokenStore, TokenSet


def build_token_set() -> TokenSet:
    now = datetime(2026, 4, 16, 10, 0, tzinfo=UTC)
    return TokenSet(
        access_token="access-123",
        refresh_token="refresh-123",
        token_type="Bearer",
        expires_at=now + timedelta(minutes=20),
        refresh_token_expires_at=now + timedelta(days=1),
        environment="sim",
        app_key_hash="app-hash",
    )


def test_file_token_store_round_trips_token_set(tmp_path):
    store = FileTokenStore(tmp_path)
    token_set = build_token_set()

    store.save("nico-saxo-bank-sim", token_set)

    loaded = store.get("nico-saxo-bank-sim")
    assert loaded == token_set


def test_file_token_store_uses_safe_profile_filename(tmp_path):
    store = FileTokenStore(tmp_path)

    store.save("../bad profile", build_token_set())

    assert store.get("../bad profile") == build_token_set()
    assert not (tmp_path.parent / "bad profile.json").exists()
    assert len(list((tmp_path / "secrets" / "saxo").glob("*.json"))) == 1


def test_file_token_store_writes_restrictive_permissions(tmp_path):
    store = FileTokenStore(tmp_path)

    store.save("nico-saxo-bank-sim", build_token_set())

    token_path = tmp_path / "secrets" / "saxo" / "nico-saxo-bank-sim.json"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_file_token_store_returns_none_for_missing_profile(tmp_path):
    store = FileTokenStore(tmp_path)

    assert store.get("missing") is None


def test_file_token_store_delete_removes_profile(tmp_path):
    store = FileTokenStore(tmp_path)
    store.save("nico-saxo-bank-sim", build_token_set())

    store.delete("nico-saxo-bank-sim")

    assert store.get("nico-saxo-bank-sim") is None


def test_file_token_store_json_does_not_include_password_fields(tmp_path):
    store = FileTokenStore(tmp_path)
    store.save("nico-saxo-bank-sim", build_token_set())

    token_path = tmp_path / "secrets" / "saxo" / "nico-saxo-bank-sim.json"
    payload = json.loads(token_path.read_text())

    assert set(payload) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_at",
        "refresh_token_expires_at",
        "environment",
        "app_key_hash",
    }
    assert "password" not in payload
    assert "app_secret" not in payload
