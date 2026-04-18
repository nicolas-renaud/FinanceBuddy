from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from financebuddy.auth.saxo_callback import CallbackResult, LocalCallbackServer


def test_local_callback_server_receives_code_and_state():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        urlopen(f"{server.redirect_uri}?code=code-123&state=state-123").read()
        result = server.wait_for_callback(timeout_seconds=2)

    assert result == CallbackResult(code="code-123", state="state-123")


def test_local_callback_server_ignores_mismatched_state_then_accepts_valid_callback():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{server.redirect_uri}?code=code-123&state=wrong-state").read()

        assert exc_info.value.code == 400

        urlopen(f"{server.redirect_uri}?code=code-123&state=state-123").read()
        result = server.wait_for_callback(timeout_seconds=2)

    assert result == CallbackResult(code="code-123", state="state-123")


def test_local_callback_server_times_out_without_callback():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        with pytest.raises(TimeoutError, match="Timed out waiting for Saxo OAuth callback"):
            server.wait_for_callback(timeout_seconds=0.1)


def test_local_callback_server_rejects_missing_code_for_matching_state():
    with LocalCallbackServer(host="127.0.0.1", port=0, path="/financebuddy", expected_state="state-123") as server:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{server.redirect_uri}?state=state-123").read()

        assert exc_info.value.code == 400

        with pytest.raises(ValueError, match="OAuth callback did not include a code"):
            server.wait_for_callback(timeout_seconds=2)
