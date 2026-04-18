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
