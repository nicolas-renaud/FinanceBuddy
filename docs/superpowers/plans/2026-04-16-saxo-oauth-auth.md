# Saxo OAuth Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure Saxo PKCE OAuth so `financebuddy crawl --connector saxo --saxo-source sim` can refresh stored tokens and automatically start browser login when reauthorization is needed.

**Architecture:** Keep Saxo OpenAPI crawling read-only by resolving an access token before constructing `RuntimeCredentials`. Add focused auth modules under `financebuddy/auth/`: token models/storage, OAuth HTTP client, and an interactive local callback login helper. The CLI remains the orchestration layer and the Saxo connector continues to receive only bearer access tokens.

**Tech Stack:** Python 3.12 standard library (`secrets`, `hashlib`, `base64`, `http.server`, `threading`, `webbrowser`, `time`, `os`, `stat`, `datetime`), `httpx`, `typer`, `pytest`.

---

## File Structure

- Create `financebuddy/auth/__init__.py`: package marker and small exports if useful.
- Create `financebuddy/auth/saxo_oauth.py`: PKCE generation, auth URL construction, token endpoint calls, token resolution workflow.
- Create `financebuddy/auth/saxo_callback.py`: loopback callback server used only during interactive login.
- Create `financebuddy/auth/token_store.py`: token dataclass and file-backed token store with restrictive permissions.
- Modify `financebuddy/cli.py`: add Saxo app key and auth flags, add `saxo-auth login`, replace token prompt for `sim` with token resolver, preserve fixture behavior and `SAXO_ACCESS_TOKEN` override.
- Modify `README.md`: document PKCE setup, 1Password env injection, automatic login-on-crawl, and `--no-auth-login`.
- Create `tests/auth/test_token_store.py`: file storage and permission behavior.
- Create `tests/auth/test_saxo_oauth.py`: PKCE, URL construction, token refresh, token resolver behavior.
- Create `tests/auth/test_saxo_callback.py`: callback success, state mismatch, timeout behavior using local HTTP requests.
- Modify `tests/test_cli.py`: cover CLI integration and preserve existing env-token behavior.

## Decisions For This Plan

- Initial token storage is file-backed only.
- The callback port defaults to `8765` and is configurable with `--saxo-auth-port`.
- FinanceBuddy prints the login URL and attempts to open the browser by default.
- First implementation requires a PKCE app and does not support `SAXO_APP_SECRET`.
- Fixture Saxo crawls keep the existing token prompt behavior for now, because fixture mode is a test/development path and does not need OAuth.

---

### Task 1: Token Store

**Files:**
- Create: `financebuddy/auth/__init__.py`
- Create: `financebuddy/auth/token_store.py`
- Create: `tests/auth/test_token_store.py`

- [ ] **Step 1: Write failing token store tests**

Create `tests/auth/test_token_store.py`:

```python
from __future__ import annotations

import json
import os
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
```

- [ ] **Step 2: Run token store tests to verify they fail**

Run:

```bash
uv run pytest tests/auth/test_token_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'financebuddy.auth'`.

- [ ] **Step 3: Implement token store**

Create `financebuddy/auth/__init__.py`:

```python
"""Authentication helpers for external finance providers."""
```

Create `financebuddy/auth/token_store.py`:

```python
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: datetime
    refresh_token_expires_at: datetime | None
    environment: str
    app_key_hash: str


class FileTokenStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "secrets" / "saxo"

    def get(self, profile_id: str) -> TokenSet | None:
        path = self._path_for(profile_id)
        if not path.exists():
            return None

        payload = json.loads(path.read_text())
        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload["token_type"],
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            refresh_token_expires_at=(
                datetime.fromisoformat(payload["refresh_token_expires_at"])
                if payload.get("refresh_token_expires_at")
                else None
            ),
            environment=payload["environment"],
            app_key_hash=payload["app_key_hash"],
        )

    def save(self, profile_id: str, token_set: TokenSet) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        path = self._path_for(profile_id)
        payload = {
            "access_token": token_set.access_token,
            "refresh_token": token_set.refresh_token,
            "token_type": token_set.token_type,
            "expires_at": token_set.expires_at.isoformat(),
            "refresh_token_expires_at": (
                token_set.refresh_token_expires_at.isoformat()
                if token_set.refresh_token_expires_at
                else None
            ),
            "environment": token_set.environment,
            "app_key_hash": token_set.app_key_hash,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.chmod(path, 0o600)

    def delete(self, profile_id: str) -> None:
        path = self._path_for(profile_id)
        if path.exists():
            path.unlink()

    def _path_for(self, profile_id: str) -> Path:
        return self._root / f"{_safe_segment(profile_id)}.json"


def _safe_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return segment or "profile"
```

- [ ] **Step 4: Run token store tests to verify they pass**

Run:

```bash
uv run pytest tests/auth/test_token_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit token store**

Run:

```bash
git add financebuddy/auth/__init__.py financebuddy/auth/token_store.py tests/auth/test_token_store.py
git commit -m "feat: add Saxo token store"
```

---

### Task 2: Saxo OAuth Client

**Files:**
- Create: `financebuddy/auth/saxo_oauth.py`
- Create: `tests/auth/test_saxo_oauth.py`

- [ ] **Step 1: Write failing OAuth client tests**

Create `tests/auth/test_saxo_oauth.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from financebuddy.auth.saxo_oauth import (
    SaxoOAuthClient,
    SaxoOAuthError,
    build_authorization_url,
    code_challenge_for,
    hash_app_key,
    new_code_verifier,
)
from financebuddy.auth.token_store import TokenSet


class DummyTransport:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def test_new_code_verifier_is_urlsafe_and_long_enough():
    verifier = new_code_verifier()

    assert len(verifier) >= 43
    assert all(char.isalnum() or char in "-._~" for char in verifier)


def test_code_challenge_for_uses_s256_known_value():
    assert code_challenge_for("abc123") == "bKE9UspwyIPg8LsQHkJaiehiTeUdstI5JZOvaoQRgJA"


def test_build_authorization_url_contains_pkce_parameters():
    url = build_authorization_url(
        authorize_url="https://sim.logonvalidation.net/authorize",
        app_key="app-key",
        redirect_uri="http://localhost:8765/financebuddy",
        state="state-123",
        code_challenge="challenge-123",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "sim.logonvalidation.net"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["app-key"]
    assert params["redirect_uri"] == ["http://localhost:8765/financebuddy"]
    assert params["state"] == ["state-123"]
    assert params["code_challenge"] == ["challenge-123"]
    assert params["code_challenge_method"] == ["S256"]


def test_exchange_code_returns_token_set():
    transport = DummyTransport(
        httpx.Response(
            200,
            json={
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "token_type": "Bearer",
                "expires_in": 1200,
                "refresh_token_expires_in": 3600,
            },
            headers={"content-type": "application/json"},
        )
    )
    client = SaxoOAuthClient(
        app_key="app-key",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    token_set = client.exchange_code(
        code="code-123",
        redirect_uri="http://localhost:8765/financebuddy",
        code_verifier="verifier-123",
    )

    assert token_set.access_token == "access-123"
    assert token_set.refresh_token == "refresh-123"
    assert token_set.expires_at == datetime(2026, 4, 16, 10, 20, tzinfo=UTC)
    assert token_set.refresh_token_expires_at == datetime(2026, 4, 16, 11, 0, tzinfo=UTC)
    request = transport.requests[0]
    assert request.url == "https://sim.logonvalidation.net/token"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert b"grant_type=authorization_code" in request.content
    assert b"code=code-123" in request.content
    assert b"code_verifier=verifier-123" in request.content


def test_refresh_token_returns_updated_token_set():
    transport = DummyTransport(
        httpx.Response(
            200,
            json={
                "access_token": "access-456",
                "refresh_token": "refresh-456",
                "token_type": "Bearer",
                "expires_in": 1200,
            },
            headers={"content-type": "application/json"},
        )
    )
    client = SaxoOAuthClient(
        app_key="app-key",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    token_set = client.refresh_token("refresh-123")

    assert token_set.access_token == "access-456"
    assert token_set.refresh_token == "refresh-456"
    assert token_set.refresh_token_expires_at is None
    assert b"grant_type=refresh_token" in transport.requests[0].content
    assert b"refresh_token=refresh-123" in transport.requests[0].content


def test_token_endpoint_errors_are_redacted():
    transport = DummyTransport(
        httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "bad refresh token secret-value"},
            headers={"content-type": "application/json"},
        )
    )
    client = SaxoOAuthClient(
        app_key="app-key",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    with pytest.raises(SaxoOAuthError) as exc_info:
        client.refresh_token("refresh-123")

    assert "400" in str(exc_info.value)
    assert "secret-value" not in str(exc_info.value)


def test_hash_app_key_is_stable_and_not_the_raw_key():
    value = hash_app_key("app-key")

    assert value == hash_app_key("app-key")
    assert value != "app-key"
```

- [ ] **Step 2: Run OAuth tests to verify they fail**

Run:

```bash
uv run pytest tests/auth/test_saxo_oauth.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'financebuddy.auth.saxo_oauth'`.

- [ ] **Step 3: Implement OAuth client**

Create `financebuddy/auth/saxo_oauth.py`:

```python
from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from financebuddy.auth.token_store import TokenSet


SIM_AUTHORIZE_URL = "https://sim.logonvalidation.net/authorize"
SIM_TOKEN_URL = "https://sim.logonvalidation.net/token"


class SaxoOAuthError(RuntimeError):
    pass


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def hash_app_key(app_key: str) -> str:
    return hashlib.sha256(app_key.encode("utf-8")).hexdigest()


def build_authorization_url(
    *,
    authorize_url: str,
    app_key: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": app_key,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{authorize_url}?{query}"


class SaxoOAuthClient:
    def __init__(
        self,
        *,
        app_key: str,
        token_url: str = SIM_TOKEN_URL,
        http_client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._app_key = app_key
        self._token_url = token_url
        self._http_client = http_client or httpx.Client()
        self._now = now or (lambda: datetime.now(UTC))

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenSet:
        response = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._app_key,
                "code_verifier": code_verifier,
            }
        )
        return self._token_set_from_response(response)

    def refresh_token(self, refresh_token: str) -> TokenSet:
        response = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._app_key,
            }
        )
        return self._token_set_from_response(response)

    def _post_token(self, data: dict[str, str]) -> dict:
        response = self._http_client.post(
            self._token_url,
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise SaxoOAuthError(f"Saxo token endpoint returned {response.status_code}")
        return response.json()

    def _token_set_from_response(self, payload: dict) -> TokenSet:
        now = self._now()
        refresh_token_expires_in = payload.get("refresh_token_expires_in")
        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_at=now + timedelta(seconds=int(payload["expires_in"])),
            refresh_token_expires_at=(
                now + timedelta(seconds=int(refresh_token_expires_in))
                if refresh_token_expires_in is not None
                else None
            ),
            environment="sim",
            app_key_hash=hash_app_key(self._app_key),
        )
```

- [ ] **Step 4: Run OAuth tests to verify they pass**

Run:

```bash
uv run pytest tests/auth/test_saxo_oauth.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit OAuth client**

Run:

```bash
git add financebuddy/auth/saxo_oauth.py tests/auth/test_saxo_oauth.py
git commit -m "feat: add Saxo OAuth client"
```

---

### Task 3: Local OAuth Callback

**Files:**
- Create: `financebuddy/auth/saxo_callback.py`
- Create: `tests/auth/test_saxo_callback.py`

- [ ] **Step 1: Write failing callback tests**

Create `tests/auth/test_saxo_callback.py`:

```python
from __future__ import annotations

import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from financebuddy.auth.saxo_callback import CallbackResult, LocalCallbackServer


def test_local_callback_server_receives_code_and_state():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        thread = threading.Thread(target=lambda: urlopen(f"{server.redirect_uri}?code=code-123&state=state-123").read())
        thread.start()

        result = server.wait_for_callback(timeout_seconds=2)
        thread.join(timeout=2)

    assert result == CallbackResult(code="code-123", state="state-123")


def test_local_callback_server_rejects_state_mismatch():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        def make_request():
            with pytest.raises(HTTPError):
                urlopen(f"{server.redirect_uri}?code=code-123&state=wrong-state").read()

        thread = threading.Thread(target=make_request)
        thread.start()

        with pytest.raises(ValueError, match="OAuth state mismatch"):
            server.wait_for_callback(timeout_seconds=2)
        thread.join(timeout=2)


def test_local_callback_server_times_out_without_callback():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        with pytest.raises(TimeoutError, match="Timed out waiting for Saxo OAuth callback"):
            server.wait_for_callback(timeout_seconds=0.1)
```

- [ ] **Step 2: Run callback tests to verify they fail**

Run:

```bash
uv run pytest tests/auth/test_saxo_callback.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'financebuddy.auth.saxo_callback'`.

- [ ] **Step 3: Implement callback server**

Create `financebuddy/auth/saxo_callback.py`:

```python
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class CallbackResult:
    code: str
    state: str


class LocalCallbackServer:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        path: str = "/financebuddy",
        expected_state: str,
    ) -> None:
        self._host = host
        self._requested_port = port
        self._path = path
        self._expected_state = expected_state
        self._queue: queue.Queue[CallbackResult | Exception] = queue.Queue(maxsize=1)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def redirect_uri(self) -> str:
        if self._server is None:
            raise RuntimeError("callback server is not running")
        host, port = self._server.server_address
        return f"http://localhost:{port}{self._path}"

    def __enter__(self) -> "LocalCallbackServer":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != outer._path:
                    self.send_error(404)
                    return

                params = parse_qs(parsed.query)
                code = params.get("code", [""])[0]
                state = params.get("state", [""])[0]
                if state != outer._expected_state:
                    outer._put_once(ValueError("OAuth state mismatch"))
                    self.send_error(400)
                    return
                if not code:
                    outer._put_once(ValueError("OAuth callback did not include a code"))
                    self.send_error(400)
                    return

                outer._put_once(CallbackResult(code=code, state=state))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"FinanceBuddy received Saxo authorization. You can close this tab.")

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        self._server = ThreadingHTTPServer((self._host, self._requested_port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def wait_for_callback(self, *, timeout_seconds: float) -> CallbackResult:
        try:
            result = self._queue.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError("Timed out waiting for Saxo OAuth callback") from exc

        if isinstance(result, Exception):
            raise result
        return result

    def _put_once(self, result: CallbackResult | Exception) -> None:
        try:
            self._queue.put_nowait(result)
        except queue.Full:
            return
```

- [ ] **Step 4: Run callback tests to verify they pass**

Run:

```bash
uv run pytest tests/auth/test_saxo_callback.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit callback server**

Run:

```bash
git add financebuddy/auth/saxo_callback.py tests/auth/test_saxo_callback.py
git commit -m "feat: add Saxo OAuth callback server"
```

---

### Task 4: Token Resolver And Interactive Login

**Files:**
- Modify: `financebuddy/auth/saxo_oauth.py`
- Modify: `tests/auth/test_saxo_oauth.py`

- [ ] **Step 1: Add failing resolver tests**

Append to `tests/auth/test_saxo_oauth.py`:

```python
from financebuddy.auth.saxo_oauth import SaxoTokenResolver


class MemoryStore:
    def __init__(self, token_set=None) -> None:
        self.token_set = token_set
        self.saved = []

    def get(self, profile_id: str):
        return self.token_set

    def save(self, profile_id: str, token_set: TokenSet) -> None:
        self.saved.append((profile_id, token_set))
        self.token_set = token_set

    def delete(self, profile_id: str) -> None:
        self.token_set = None


def test_resolver_uses_access_token_override_without_store_access():
    class FailingStore:
        def get(self, profile_id: str):
            raise AssertionError("store should not be read")

    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=FailingStore(),
        oauth_client=None,
        interactive_login=None,
    )

    assert resolver.resolve_access_token(
        profile_id="nico-saxo-bank-sim",
        access_token_override="override-token",
        allow_interactive_login=False,
    ) == "override-token"


def test_resolver_refreshes_stored_token_and_saves_replacement():
    old_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )
    new_token = TokenSet(
        access_token="new-access",
        refresh_token="new-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )

    class FakeOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            assert refresh_token == "old-refresh"
            return new_token

    store = MemoryStore(old_token)
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=FakeOAuthClient(),
        interactive_login=None,
    )

    assert resolver.resolve_access_token(
        profile_id="nico-saxo-bank-sim",
        access_token_override=None,
        allow_interactive_login=False,
    ) == "new-access"
    assert store.saved == [("nico-saxo-bank-sim", new_token)]


def test_resolver_interactive_login_when_no_token_exists():
    login_token = TokenSet(
        access_token="login-access",
        refresh_token="login-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )

    store = MemoryStore()
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=None,
        interactive_login=lambda: login_token,
    )

    assert resolver.resolve_access_token(
        profile_id="nico-saxo-bank-sim",
        access_token_override=None,
        allow_interactive_login=True,
    ) == "login-access"
    assert store.saved == [("nico-saxo-bank-sim", login_token)]


def test_resolver_fails_when_no_token_and_login_disabled():
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=MemoryStore(),
        oauth_client=None,
        interactive_login=None,
    )

    with pytest.raises(SaxoOAuthError, match="No Saxo refresh token is stored"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=False,
        )


def test_resolver_interactive_login_when_refresh_is_rejected():
    old_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )
    login_token = TokenSet(
        access_token="login-access",
        refresh_token="login-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )

    class RejectingOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            raise SaxoOAuthError("Saxo token endpoint returned 400")

    store = MemoryStore(old_token)
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=RejectingOAuthClient(),
        interactive_login=lambda: login_token,
    )

    assert resolver.resolve_access_token(
        profile_id="nico-saxo-bank-sim",
        access_token_override=None,
        allow_interactive_login=True,
    ) == "login-access"
    assert store.saved == [("nico-saxo-bank-sim", login_token)]
```

- [ ] **Step 2: Run resolver tests to verify they fail**

Run:

```bash
uv run pytest tests/auth/test_saxo_oauth.py -v
```

Expected: FAIL with `ImportError` for `SaxoTokenResolver`.

- [ ] **Step 3: Implement resolver and interactive login helper**

Append to `financebuddy/auth/saxo_oauth.py`:

```python
from collections.abc import Protocol
import webbrowser

from financebuddy.auth.saxo_callback import LocalCallbackServer


class TokenStore(Protocol):
    def get(self, profile_id: str) -> TokenSet | None: ...
    def save(self, profile_id: str, token_set: TokenSet) -> None: ...
    def delete(self, profile_id: str) -> None: ...


class SaxoTokenResolver:
    def __init__(
        self,
        *,
        app_key: str,
        store: TokenStore,
        oauth_client,
        interactive_login,
    ) -> None:
        self._app_key = app_key
        self._store = store
        self._oauth_client = oauth_client
        self._interactive_login = interactive_login

    def resolve_access_token(
        self,
        *,
        profile_id: str,
        access_token_override: str | None,
        allow_interactive_login: bool,
    ) -> str:
        if access_token_override:
            return access_token_override

        stored = self._store.get(profile_id)
        if stored is not None:
            if stored.app_key_hash != hash_app_key(self._app_key):
                raise SaxoOAuthError("Stored Saxo token belongs to a different app key")
            try:
                refreshed = self._oauth_client.refresh_token(stored.refresh_token)
            except SaxoOAuthError:
                if not allow_interactive_login:
                    raise
            else:
                self._store.save(profile_id, refreshed)
                return refreshed.access_token

        if not allow_interactive_login:
            raise SaxoOAuthError(
                "No Saxo refresh token is stored. Run without --no-auth-login or run `financebuddy saxo-auth login`."
            )
        if self._interactive_login is None:
            raise SaxoOAuthError("Interactive Saxo login is not configured")

        token_set = self._interactive_login()
        self._store.save(profile_id, token_set)
        return token_set.access_token


def run_interactive_pkce_login(
    *,
    app_key: str,
    oauth_client: SaxoOAuthClient,
    host: str = "127.0.0.1",
    port: int = 8765,
    path: str = "/financebuddy",
    timeout_seconds: float = 180,
    open_browser: bool = True,
    echo=print,
) -> TokenSet:
    state = new_state()
    verifier = new_code_verifier()
    challenge = code_challenge_for(verifier)

    with LocalCallbackServer(
        host=host,
        port=port,
        path=path,
        expected_state=state,
    ) as callback:
        authorization_url = build_authorization_url(
            authorize_url=SIM_AUTHORIZE_URL,
            app_key=app_key,
            redirect_uri=callback.redirect_uri,
            state=state,
            code_challenge=challenge,
        )
        echo("Open this Saxo authorization URL to continue:")
        echo(authorization_url)
        if open_browser:
            webbrowser.open(authorization_url)

        result = callback.wait_for_callback(timeout_seconds=timeout_seconds)

    return oauth_client.exchange_code(
        code=result.code,
        redirect_uri=callback.redirect_uri,
        code_verifier=verifier,
    )
```

- [ ] **Step 4: Run resolver tests to verify they pass**

Run:

```bash
uv run pytest tests/auth/test_saxo_oauth.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all auth tests**

Run:

```bash
uv run pytest tests/auth -v
```

Expected: PASS.

- [ ] **Step 6: Commit resolver**

Run:

```bash
git add financebuddy/auth/saxo_oauth.py tests/auth/test_saxo_oauth.py
git commit -m "feat: resolve Saxo access tokens"
```

---

### Task 5: CLI Integration

**Files:**
- Modify: `financebuddy/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests for auth behavior**

Append to `tests/test_cli.py`:

```python
def test_saxo_auth_login_command_saves_token(tmp_path: Path, monkeypatch) -> None:
    calls = {}

    class FakeStore:
        def __init__(self, data_dir):
            calls["data_dir"] = data_dir
            self.saved = []

        def save(self, profile_id, token_set):
            calls["saved"] = (profile_id, token_set.access_token)

    class FakeToken:
        access_token = "access-from-login"

    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    monkeypatch.setattr("financebuddy.cli.FileTokenStore", FakeStore)
    monkeypatch.setattr("financebuddy.cli.SaxoOAuthClient", lambda app_key: object())
    monkeypatch.setattr(
        "financebuddy.cli.run_interactive_pkce_login",
        lambda **kwargs: FakeToken(),
    )

    result = runner.invoke(
        app,
        [
            "saxo-auth",
            "login",
            "--data-dir",
            str(tmp_path),
            "--owner",
            "nico",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0
    assert calls["data_dir"] == tmp_path
    assert calls["saved"] == ("nico-saxo-bank-sim", "access-from-login")
    assert "Saxo authorization saved for nico-saxo-bank-sim" in result.stdout


def test_saxo_sim_crawl_uses_token_resolver_when_env_token_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    captured = {}

    class FakeResolver:
        def __init__(self, **kwargs):
            captured["resolver_kwargs"] = kwargs

        def resolve_access_token(self, **kwargs):
            captured["resolve_kwargs"] = kwargs
            return "resolved-token"

    monkeypatch.setattr("financebuddy.cli.SaxoTokenResolver", FakeResolver)
    monkeypatch.setattr("financebuddy.cli.FileTokenStore", lambda data_dir: object())
    monkeypatch.setattr("financebuddy.cli.SaxoOAuthClient", lambda app_key: object())
    monkeypatch.setattr("financebuddy.cli.run_interactive_pkce_login", lambda **kwargs: None)
    monkeypatch.setattr("financebuddy.cli._build_saxo_sim_connector", lambda: object())
    def fake_run_crawl(**kwargs):
        captured["credentials"] = kwargs["credentials"]
        return {"accounts": [], "balances": [], "positions": [], "warnings": []}

    monkeypatch.setattr("financebuddy.cli.run_crawl", fake_run_crawl)

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "sim",
            "--owner",
            "nico",
        ],
    )

    assert result.exit_code == 0
    assert captured["resolve_kwargs"] == {
        "profile_id": "nico-saxo-bank-sim",
        "access_token_override": None,
        "allow_interactive_login": True,
    }
    assert captured["credentials"].access_token == "resolved-token"


def test_saxo_sim_crawl_no_auth_login_disables_interactive_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SAXO_APP_KEY", "app-key")
    captured = {}

    class FakeResolver:
        def __init__(self, **kwargs):
            pass

        def resolve_access_token(self, **kwargs):
            captured.update(kwargs)
            return "resolved-token"

    monkeypatch.setattr("financebuddy.cli.SaxoTokenResolver", FakeResolver)
    monkeypatch.setattr("financebuddy.cli.FileTokenStore", lambda data_dir: object())
    monkeypatch.setattr("financebuddy.cli.SaxoOAuthClient", lambda app_key: object())
    monkeypatch.setattr("financebuddy.cli.run_interactive_pkce_login", lambda **kwargs: None)
    monkeypatch.setattr("financebuddy.cli._build_saxo_sim_connector", lambda: object())
    monkeypatch.setattr(
        "financebuddy.cli.run_crawl",
        lambda **kwargs: {"accounts": [], "balances": [], "positions": [], "warnings": []},
    )

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "sim",
            "--owner",
            "nico",
            "--no-auth-login",
        ],
    )

    assert result.exit_code == 0
    assert captured["allow_interactive_login"] is False


def test_saxo_sim_crawl_requires_app_key_without_env_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SAXO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SAXO_APP_KEY", raising=False)

    result = runner.invoke(
        app,
        [
            "crawl",
            "--data-dir",
            str(tmp_path),
            "--connector",
            "saxo",
            "--saxo-source",
            "sim",
            "--owner",
            "nico",
            "--no-auth-login",
        ],
    )

    assert result.exit_code == 2
    assert "SAXO_APP_KEY is required" in result.output
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py -v
```

Expected: FAIL because `saxo-auth`, `--no-auth-login`, and resolver wiring do not exist.

- [ ] **Step 3: Modify CLI imports and command groups**

In `financebuddy/cli.py`, add imports:

```python
from financebuddy.auth.saxo_oauth import (
    SaxoOAuthClient,
    SaxoOAuthError,
    SaxoTokenResolver,
    run_interactive_pkce_login,
)
from financebuddy.auth.token_store import FileTokenStore
```

After `app = typer.Typer(...)`, add:

```python
saxo_auth_app = typer.Typer(help="Saxo authentication commands.")
app.add_typer(saxo_auth_app, name="saxo-auth")
```

- [ ] **Step 4: Add crawl auth options**

In the `crawl(...)` signature in `financebuddy/cli.py`, add:

```python
    saxo_app_key: str | None = typer.Option(
        None,
        "--saxo-app-key",
        help="Saxo OpenAPI app key. Defaults to SAXO_APP_KEY.",
    ),
    auth_login: bool = typer.Option(
        True,
        "--auth-login/--no-auth-login",
        help="Allow interactive Saxo OAuth login when no usable refresh token exists.",
    ),
    saxo_auth_port: int = typer.Option(
        8765,
        "--saxo-auth-port",
        help="Localhost port for Saxo OAuth callback.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Open the Saxo OAuth URL in the default browser.",
    ),
```

- [ ] **Step 5: Replace Saxo SIM token prompt with resolver**

In the `elif connector == "saxo":` branch, keep fixture mode token prompt unchanged. For `saxo_source == "sim"`, build the profile before resolving the token and use:

```python
        profile = AccessProfile(
            profile_id=f"{owner}-saxo-bank-sim",
            connector_id="saxo_bank_api",
            institution_slug="saxo-bank",
            owner_slug=owner,
        )

        access_token = os.environ.get("SAXO_ACCESS_TOKEN")
        if saxo_source == "sim":
            access_token = _resolve_saxo_sim_access_token(
                data_dir=config.data_dir,
                profile_id=profile.profile_id,
                app_key=saxo_app_key or os.environ.get("SAXO_APP_KEY"),
                access_token_override=access_token,
                allow_interactive_login=auth_login,
                auth_port=saxo_auth_port,
                open_browser=open_browser,
            )
        elif not access_token:
            access_token = typer.prompt("Access token", hide_input=True)

        credentials = RuntimeCredentials(
            username=owner,
            password="",
            access_token=access_token,
        )
```

Remove the older duplicate profile and credential construction in that branch.

- [ ] **Step 6: Add CLI auth helpers**

Append to `financebuddy/cli.py`:

```python
@saxo_auth_app.command("login")
def saxo_auth_login(
    data_dir: Path = typer.Option(..., exists=False),
    owner: str = typer.Option(..., help="Saxo owner slug used to build the access profile."),
    saxo_app_key: str | None = typer.Option(
        None,
        "--saxo-app-key",
        help="Saxo OpenAPI app key. Defaults to SAXO_APP_KEY.",
    ),
    saxo_auth_port: int = typer.Option(
        8765,
        "--saxo-auth-port",
        help="Localhost port for Saxo OAuth callback.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-open-browser",
        help="Open the Saxo OAuth URL in the default browser.",
    ),
) -> None:
    config = load_config(data_dir)
    profile_id = f"{owner}-saxo-bank-sim"
    app_key = saxo_app_key or os.environ.get("SAXO_APP_KEY")
    if not app_key:
        raise typer.BadParameter("SAXO_APP_KEY is required for Saxo OAuth login")

    oauth_client = SaxoOAuthClient(app_key=app_key)
    token_set = run_interactive_pkce_login(
        app_key=app_key,
        oauth_client=oauth_client,
        port=saxo_auth_port,
        open_browser=open_browser,
        echo=typer.echo,
    )
    FileTokenStore(config.data_dir).save(profile_id, token_set)
    typer.echo(f"Saxo authorization saved for {profile_id}")


def _resolve_saxo_sim_access_token(
    *,
    data_dir: Path,
    profile_id: str,
    app_key: str | None,
    access_token_override: str | None,
    allow_interactive_login: bool,
    auth_port: int,
    open_browser: bool,
) -> str:
    if access_token_override:
        return access_token_override
    if not app_key:
        raise typer.BadParameter("SAXO_APP_KEY is required for Saxo OAuth login")

    oauth_client = SaxoOAuthClient(app_key=app_key)
    resolver = SaxoTokenResolver(
        app_key=app_key,
        store=FileTokenStore(data_dir),
        oauth_client=oauth_client,
        interactive_login=lambda: run_interactive_pkce_login(
            app_key=app_key,
            oauth_client=oauth_client,
            port=auth_port,
            open_browser=open_browser,
            echo=typer.echo,
        ),
    )
    try:
        return resolver.resolve_access_token(
            profile_id=profile_id,
            access_token_override=None,
            allow_interactive_login=allow_interactive_login,
        )
    except SaxoOAuthError as exc:
        raise typer.BadParameter(str(exc)) from exc
```

- [ ] **Step 7: Run targeted CLI tests**

Run:

```bash
uv run pytest tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 8: Run auth and CLI tests**

Run:

```bash
uv run pytest tests/auth tests/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit CLI integration**

Run:

```bash
git add financebuddy/cli.py tests/test_cli.py
git commit -m "feat: wire Saxo OAuth into CLI"
```

---

### Task 6: Documentation And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README Saxo SIM instructions**

Replace the current `## Run Saxo SIM Crawl` section in `README.md` with:

```markdown
## Run Saxo SIM Crawl

Create a Saxo OpenAPI simulation app with:

- Grant type: PKCE
- Trading enabled: no
- Redirect URL: `http://localhost/financebuddy`

Provide the app key with an environment variable:

```bash
export SAXO_APP_KEY='<your-saxo-app-key>'
```

Then run the crawl:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner>
```

If FinanceBuddy has no usable Saxo refresh token, it prints a Saxo authorization
URL, opens the browser when possible, waits for the localhost callback, stores
the returned refresh token under `data/secrets/saxo/`, and continues the crawl.
Later crawls refresh the access token automatically.

For non-interactive jobs, disable browser login:

```bash
uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner> \
  --no-auth-login
```

You can also authorize explicitly:

```bash
uv run financebuddy saxo-auth login \
  --data-dir ./data \
  --owner <owner>
```

`SAXO_ACCESS_TOKEN` remains supported as an explicit short-lived override for
development. Do not commit app keys, tokens, or files under `data/secrets/`.

With 1Password, inject `SAXO_APP_KEY` at runtime:

```bash
op run --env-file .env.1password -- uv run financebuddy crawl \
  --data-dir ./data \
  --connector saxo \
  --saxo-source sim \
  --owner <owner>
```
```

- [ ] **Step 2: Run docs-related CLI help check**

Run:

```bash
uv run financebuddy crawl --help
uv run financebuddy saxo-auth login --help
```

Expected: both commands print help successfully. Help for crawl includes `--no-auth-login`, `--saxo-app-key`, `--saxo-auth-port`, and `--no-open-browser`.

- [ ] **Step 3: Run targeted test suite**

Run:

```bash
uv run pytest tests/auth tests/test_cli.py tests/connectors/test_saxo_bank_api.py -v
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Inspect git diff for secret leakage**

Run:

```bash
git diff -- README.md financebuddy/auth financebuddy/cli.py tests/auth tests/test_cli.py
```

Expected: no real Saxo app keys, app secrets, access tokens, refresh tokens, authorization codes, or password values appear in the diff. Test values such as `access-123`, `refresh-123`, and `app-key` are acceptable.

- [ ] **Step 6: Commit docs and final polish**

Run:

```bash
git add README.md
git commit -m "docs: document Saxo OAuth setup"
```

---

## Final Verification Checklist

- [ ] `uv run pytest -q` passes.
- [ ] `uv run financebuddy crawl --help` includes the new Saxo auth options.
- [ ] `uv run financebuddy saxo-auth login --help` succeeds.
- [ ] `SAXO_ACCESS_TOKEN` still bypasses token store and OAuth.
- [ ] Saxo fixture mode still works with fixture data.
- [ ] Saxo SIM mode fails clearly when no `SAXO_APP_KEY` is configured and no `SAXO_ACCESS_TOKEN` override is present.
- [ ] Saxo SIM mode can refresh a stored token without browser login.
- [ ] Saxo SIM mode can start browser login when refresh is missing or rejected.
- [ ] Token files are written outside snapshots and with `0600` permissions.
- [ ] No sensitive values are logged, committed, or stored in SQLite crawl data.
