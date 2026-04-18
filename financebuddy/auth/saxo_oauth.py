from __future__ import annotations

import base64
import hashlib
import webbrowser
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

import httpx

from financebuddy.auth.saxo_callback import LocalCallbackServer
from financebuddy.auth.token_store import TokenSet

SIM_AUTHORIZE_URL = "https://sim.logonvalidation.net/authorize"
SIM_TOKEN_URL = "https://sim.logonvalidation.net/token"


class SaxoOAuthError(RuntimeError):
    pass


class TokenStore(Protocol):
    def get(self, profile_id: str) -> TokenSet | None: ...

    def save(self, profile_id: str, token_set: TokenSet) -> None: ...

    def delete(self, profile_id: str) -> None: ...


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
            access_token = _require_non_empty_string(data["access_token"], "access_token")
            refresh_token = _require_non_empty_string(data["refresh_token"], "refresh_token")
            token_type = _require_non_empty_string(data["token_type"], "token_type")
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


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise SaxoOAuthError(
            f"Saxo token endpoint returned an invalid token response: {field_name}"
        )
    return value


class SaxoTokenResolver:
    def __init__(
        self,
        *,
        app_key: str,
        store: TokenStore,
        oauth_client: SaxoOAuthClient | None,
        interactive_login: Callable[[], TokenSet] | None,
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

        stored_token = self._store.get(profile_id)
        if stored_token is not None:
            if stored_token.app_key_hash != hash_app_key(self._app_key):
                raise SaxoOAuthError(
                    "Stored Saxo token belongs to a different app key"
                )

            try:
                refreshed_token = self._refresh_stored_token(stored_token, profile_id)
            except SaxoOAuthError:
                if not allow_interactive_login:
                    raise
                return self._run_interactive_login(profile_id)

            return refreshed_token.access_token

        if not allow_interactive_login:
            raise SaxoOAuthError(
                "No Saxo refresh token is stored. Run without --no-auth-login or run `financebuddy saxo-auth login`."
            )

        return self._run_interactive_login(profile_id)

    def _refresh_stored_token(
        self,
        stored_token: TokenSet,
        profile_id: str,
    ) -> TokenSet:
        if self._oauth_client is None:
            raise SaxoOAuthError("Saxo OAuth client is not configured")

        refreshed_token = self._oauth_client.refresh_token(stored_token.refresh_token)
        self._ensure_token_matches_app_key(refreshed_token)
        self._store.save(profile_id, refreshed_token)
        return refreshed_token

    def _run_interactive_login(self, profile_id: str) -> str:
        if self._interactive_login is None:
            raise SaxoOAuthError("Interactive Saxo login is not configured")

        token_set = self._interactive_login()
        self._ensure_token_matches_app_key(token_set)
        self._store.save(profile_id, token_set)
        return token_set.access_token

    def _ensure_token_matches_app_key(self, token_set: TokenSet) -> None:
        if token_set.app_key_hash != hash_app_key(self._app_key):
            raise SaxoOAuthError("Stored Saxo token belongs to a different app key")


def run_interactive_pkce_login(
    *,
    app_key: str,
    oauth_client: SaxoOAuthClient,
    host: str = "127.0.0.1",
    port: int = 8765,
    path: str = "/financebuddy",
    timeout_seconds: float = 180,
    open_browser: bool = True,
    echo: Callable[[str], object] = print,
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
            app_key=app_key,
            redirect_uri=callback.redirect_uri,
            state=state,
            code_challenge=challenge,
        )
        echo("Open this Saxo authorization URL to continue:")
        echo(authorization_url)
        if open_browser:
            webbrowser.open(authorization_url)

        result = callback.wait_for_callback(timeout_seconds)

    return oauth_client.exchange_code(
        code=result.code,
        redirect_uri=callback.redirect_uri,
        code_verifier=verifier,
    )
