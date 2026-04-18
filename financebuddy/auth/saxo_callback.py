from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from threading import Event, Thread
from typing import ClassVar
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class CallbackResult:
    code: str
    state: str


class LocalCallbackServer:
    _success_message: ClassVar[bytes] = b"Saxo OAuth login complete. You can close this tab."

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        path: str = "/financebuddy",
        expected_state: str,
    ) -> None:
        self._host = host
        self._port = port
        self._path = _normalize_path(path)
        self._expected_state = expected_state
        self._callback_queue: Queue[CallbackResult | BaseException] = Queue()
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._started = Event()

    def __enter__(self) -> "LocalCallbackServer":
        handler = self._handler_class()
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._server.daemon_threads = True
        self._thread = Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._started.wait(timeout=1)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def redirect_uri(self) -> str:
        if self._server is None:
            raise RuntimeError("LocalCallbackServer must be started before use")
        return f"http://localhost:{self._server.server_address[1]}{self._path}"

    def wait_for_callback(self, timeout_seconds: float) -> CallbackResult:
        try:
            item = self._callback_queue.get(timeout=timeout_seconds)
        except Empty as exc:
            raise TimeoutError("Timed out waiting for Saxo OAuth callback") from exc

        if isinstance(item, BaseException):
            raise item
        return item

    def _serve(self) -> None:
        self._started.set()
        if self._server is not None:
            self._server.serve_forever(poll_interval=0.1)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                parsed = urlparse(self.path)
                if parsed.path != outer._path:
                    self.send_error(404)
                    return

                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]
                if state != outer._expected_state:
                    outer._callback_queue.put(ValueError("OAuth state mismatch"))
                    self._send_text_response(400, b"OAuth state mismatch")
                    return

                code = params.get("code", [""])[0]
                if code == "":
                    outer._callback_queue.put(ValueError("OAuth callback did not include a code"))
                    self._send_text_response(400, b"OAuth callback did not include a code")
                    return

                outer._callback_queue.put(CallbackResult(code=code, state=state))
                self._send_text_response(200, outer._success_message)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def _send_text_response(self, status_code: int, message: bytes) -> None:
                self.send_response(status_code)
                self.send_header("content-type", "text/plain; charset=utf-8")
                self.send_header("content-length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)

        return CallbackHandler


def _normalize_path(path: str) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return normalized.rstrip("/") or "/"
