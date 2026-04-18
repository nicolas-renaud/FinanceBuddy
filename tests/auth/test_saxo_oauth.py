from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from financebuddy.auth.saxo_oauth import (
    SaxoOAuthClient,
    SaxoOAuthError,
    SaxoTokenResolver,
    build_authorization_url,
    code_challenge_for,
    hash_app_key,
    new_code_verifier,
    run_interactive_pkce_login,
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


def test_successful_token_response_requires_an_object():
    transport = DummyTransport(
        httpx.Response(
            200,
            json=["not", "an", "object"],
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

    assert "token response" in str(exc_info.value)


def test_successful_token_response_requires_mandatory_fields():
    transport = DummyTransport(
        httpx.Response(
            200,
            json={
                "access_token": "access-123",
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

    with pytest.raises(SaxoOAuthError) as exc_info:
        client.refresh_token("refresh-123")

    assert "token response" in str(exc_info.value)


def test_successful_token_response_requires_numeric_expires_in():
    transport = DummyTransport(
        httpx.Response(
            200,
            json={
                "access_token": "access-123",
                "refresh_token": "refresh-123",
                "token_type": "Bearer",
                "expires_in": "not-a-number",
            },
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

    assert "token response" in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token", None),
        ("access_token", 123),
        ("access_token", ""),
        ("refresh_token", None),
        ("refresh_token", 123),
        ("refresh_token", ""),
        ("token_type", None),
        ("token_type", 123),
        ("token_type", ""),
    ],
)
def test_successful_token_response_requires_non_empty_string_token_fields(field, value):
    payload = {
        "access_token": "access-123",
        "refresh_token": "refresh-123",
        "token_type": "Bearer",
        "expires_in": 1200,
    }
    payload[field] = value
    transport = DummyTransport(
        httpx.Response(
            200,
            json=payload,
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

    assert "token response" in str(exc_info.value)
    assert "access-123" not in str(exc_info.value)
    assert "refresh-123" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)


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


def test_resolver_rejects_refreshed_token_from_different_app_key_without_saving():
    old_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )
    replacement_token = TokenSet(
        access_token="replacement-access",
        refresh_token="replacement-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("other-app-key"),
    )

    class FakeOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            assert refresh_token == "old-refresh"
            return replacement_token

    store = MemoryStore(old_token)
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=FakeOAuthClient(),
        interactive_login=None,
    )

    with pytest.raises(SaxoOAuthError, match="different app key"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=False,
        )

    assert store.saved == []
    assert store.token_set == old_token


def test_resolver_rejects_refreshed_token_mismatch_without_falling_back_to_login():
    old_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )
    replacement_token = TokenSet(
        access_token="replacement-access",
        refresh_token="replacement-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("other-app-key"),
    )

    class FakeOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            assert refresh_token == "old-refresh"
            return replacement_token

    login_called = []

    def interactive_login():
        login_called.append(True)
        raise AssertionError("login should not be called")

    store = MemoryStore(old_token)
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=FakeOAuthClient(),
        interactive_login=interactive_login,
    )

    with pytest.raises(SaxoOAuthError, match="different app key"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=True,
        )

    assert login_called == []
    assert store.saved == []
    assert store.token_set == old_token


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


def test_resolver_rejects_interactive_token_from_different_app_key_without_saving():
    login_token = TokenSet(
        access_token="login-access",
        refresh_token="login-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("other-app-key"),
    )

    store = MemoryStore()
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=None,
        interactive_login=lambda: login_token,
    )

    with pytest.raises(SaxoOAuthError, match="different app key"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=True,
        )

    assert store.saved == []
    assert store.token_set is None


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


def test_resolver_refresh_failure_with_login_disabled_propagates_and_does_not_overwrite_or_login():
    old_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("app-key"),
    )

    class RejectingOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            raise SaxoOAuthError("Saxo token endpoint returned 400")

    login_called = []

    def interactive_login():
        login_called.append(True)
        raise AssertionError("login should not be called")

    store = MemoryStore(old_token)
    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=store,
        oauth_client=RejectingOAuthClient(),
        interactive_login=interactive_login,
    )

    with pytest.raises(SaxoOAuthError, match="400"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=False,
        )

    assert login_called == []
    assert store.saved == []
    assert store.token_set == old_token


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


def test_resolver_rejects_token_from_different_app_key_without_refresh_or_login():
    stored_token = TokenSet(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
        refresh_token_expires_at=None,
        environment="sim",
        app_key_hash=hash_app_key("other-app-key"),
    )

    class FailingOAuthClient:
        def refresh_token(self, refresh_token: str) -> TokenSet:
            raise AssertionError("refresh should not be called")

    login_called = []

    def interactive_login():
        login_called.append(True)
        raise AssertionError("login should not be called")

    resolver = SaxoTokenResolver(
        app_key="app-key",
        store=MemoryStore(stored_token),
        oauth_client=FailingOAuthClient(),
        interactive_login=interactive_login,
    )

    with pytest.raises(SaxoOAuthError, match="different app key"):
        resolver.resolve_access_token(
            profile_id="nico-saxo-bank-sim",
            access_token_override=None,
            allow_interactive_login=True,
        )

    assert login_called == []


def test_run_interactive_pkce_login_opens_browser_and_exchanges_callback_code(monkeypatch, capsys):
    callback_created = []
    open_calls = []

    class FakeCallbackServer:
        def __init__(self, *, host, port, path, expected_state) -> None:
            callback_created.append(
                {
                    "host": host,
                    "port": port,
                    "path": path,
                    "expected_state": expected_state,
                }
            )
            self.redirect_uri = "http://localhost:8765/financebuddy"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def wait_for_callback(self, timeout_seconds: float):
            return type("CallbackResult", (), {"code": "callback-code", "state": "callback-state"})()

    monkeypatch.setattr("financebuddy.auth.saxo_oauth.LocalCallbackServer", FakeCallbackServer)
    monkeypatch.setattr("financebuddy.auth.saxo_oauth.new_state", lambda: "state-123")
    monkeypatch.setattr("financebuddy.auth.saxo_oauth.new_code_verifier", lambda: "verifier-123")
    monkeypatch.setattr("financebuddy.auth.saxo_oauth.webbrowser.open", lambda url: open_calls.append(url))

    class FakeOAuthClient:
        def __init__(self) -> None:
            self.calls = []

        def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
            self.calls.append(
                {
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                }
            )
            return TokenSet(
                access_token="access-123",
                refresh_token="refresh-123",
                token_type="Bearer",
                expires_at=datetime(2026, 4, 16, 10, 20, tzinfo=UTC),
                refresh_token_expires_at=None,
                environment="sim",
                app_key_hash=hash_app_key("app-key"),
            )

    oauth_client = FakeOAuthClient()

    token_set = run_interactive_pkce_login(
        app_key="app-key",
        oauth_client=oauth_client,
        open_browser=True,
        echo=print,
    )

    captured = capsys.readouterr().out
    assert "Open this Saxo authorization URL to continue:" in captured
    assert "access-123" not in captured
    assert "refresh-123" not in captured
    assert len(open_calls) == 1
    parsed = urlparse(open_calls[0])
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "sim.logonvalidation.net"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["app-key"]
    assert params["redirect_uri"] == ["http://localhost:8765/financebuddy"]
    assert params["state"] == ["state-123"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [code_challenge_for("verifier-123")]
    assert oauth_client.calls == [
        {
            "code": "callback-code",
            "redirect_uri": "http://localhost:8765/financebuddy",
            "code_verifier": "verifier-123",
        }
    ]
    assert token_set.access_token == "access-123"
    assert callback_created == [
        {
            "host": "127.0.0.1",
            "port": 8765,
            "path": "/financebuddy",
            "expected_state": "state-123",
        }
    ]


def test_client_close_closes_owned_http_client():
    client = SaxoOAuthClient(
        app_key="app-key",
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    client.close()

    assert client._http_client.is_closed is True


def test_client_close_does_not_close_injected_http_client():
    http_client = httpx.Client()
    client = SaxoOAuthClient(
        app_key="app-key",
        http_client=http_client,
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    client.close()

    assert client._http_client.is_closed is False
    assert http_client.is_closed is False
    http_client.close()


def test_client_supports_context_manager_for_owned_client():
    with SaxoOAuthClient(
        app_key="app-key",
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    ) as client:
        assert isinstance(client, SaxoOAuthClient)


def test_hash_app_key_is_stable_and_not_the_raw_key():
    value = hash_app_key("app-key")

    assert value == hash_app_key("app-key")
    assert value != "app-key"
