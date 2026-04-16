from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
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
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_app_key(app_key: str) -> str:
    return hashlib.sha256(app_key.encode("utf-8")).hexdigest()


def build_authorization_url(
    *,
    authorize_url: str = SIM_AUTHORIZE_URL,
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
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client()
        self._now = now or (lambda: datetime.now(tz=UTC))

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenSet:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self._app_key,
        }
        response = self._post_token(payload)
        data = self._parse_response(response)
        return self._token_set_from_response(data)

    def refresh_token(self, refresh_token: str) -> TokenSet:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._app_key,
        }
        response = self._post_token(payload)
        data = self._parse_response(response)
        return self._token_set_from_response(data)

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> "SaxoOAuthClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.close()

    def _post_token(self, payload: dict[str, str]) -> httpx.Response:
        response = self._http_client.post(self._token_url, data=payload)
        if response.status_code >= 400:
            raise SaxoOAuthError(
                f"Saxo token endpoint returned HTTP {response.status_code}"
            )
        return response

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - defensive parsing
            raise SaxoOAuthError("Saxo token endpoint returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise SaxoOAuthError("Saxo token endpoint returned an invalid token response")
        return data

    def _token_set_from_response(self, data: dict[str, Any]) -> TokenSet:
        now = self._now()
        try:
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            token_type = data["token_type"]
            expires_in = int(data["expires_in"])
            refresh_token_expires_in = data.get("refresh_token_expires_in")
            refresh_token_expires_at = (
                now + timedelta(seconds=int(refresh_token_expires_in))
                if refresh_token_expires_in is not None
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SaxoOAuthError(
                "Saxo token endpoint returned an invalid token response"
            ) from exc

        return TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            expires_at=now + timedelta(seconds=expires_in),
            refresh_token_expires_at=refresh_token_expires_at,
            environment="sim",
            app_key_hash=hash_app_key(self._app_key),
        )
