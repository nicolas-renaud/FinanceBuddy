from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from financebuddy.auth.token_store import FileTokenStore, TokenSet

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX permissions are local-only",
)


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

    secrets_dir = tmp_path / "secrets"
    saxo_dir = tmp_path / "secrets" / "saxo"
    token_path = store._path_for_profile("nico-saxo-bank-sim")
    assert stat.S_IMODE(secrets_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(saxo_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_file_token_store_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    store = FileTokenStore(tmp_path)

    store.save("nico-saxo-bank-sim", build_token_set())

    saxo_dir = tmp_path / "secrets" / "saxo"
    token_path = store._path_for_profile("nico-saxo-bank-sim")
    assert not list(saxo_dir.glob("*.tmp"))
    assert token_path.exists()


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

    token_path = store._path_for_profile("nico-saxo-bank-sim")
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


def test_file_token_store_uses_separate_files_for_colliding_profile_ids(tmp_path):
    store = FileTokenStore(tmp_path)
    alice_saxo = build_token_set()
    alice_colon_saxo = replace(alice_saxo, access_token="access-456")

    store.save("alice/saxo", alice_saxo)
    store.save("alice:saxo", alice_colon_saxo)

    saxo_dir = tmp_path / "secrets" / "saxo"
    filenames = sorted(path.name for path in saxo_dir.glob("*.json"))

    assert len(filenames) == 2
    assert filenames[0] != filenames[1]
    assert store.get("alice/saxo") == alice_saxo
    assert store.get("alice:saxo") == alice_colon_saxo
