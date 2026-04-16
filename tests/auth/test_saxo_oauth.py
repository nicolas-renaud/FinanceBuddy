from __future__ import annotations

from datetime import UTC, datetime
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


def test_client_close_closes_owned_http_client():
    client = SaxoOAuthClient(
        app_key="app-key",
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    client.close()


def test_client_close_does_not_close_injected_http_client():
    http_client = httpx.Client()
    client = SaxoOAuthClient(
        app_key="app-key",
        http_client=http_client,
        now=lambda: datetime(2026, 4, 16, 10, 0, tzinfo=UTC),
    )

    client.close()

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
