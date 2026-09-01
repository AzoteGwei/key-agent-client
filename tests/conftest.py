"""A stand-in server, so the tests need no JVM.

The point of testing against a fake is not speed. It is that these tests are about this client:
what it sends, what it does with what comes back, and what it refuses to invent. A real KeY would
make the interesting cases — a task that fails, a proof that does not close — hard to arrange and
slow to reach, and would test KeY rather than the client.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest


class FakeServer:
    """A JSON-RPC endpoint that answers from a script of canned replies."""

    def __init__(self) -> None:
        self.replies: dict[str, Any] = {}
        self.errors: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.events: list[str] = []
        self._server = HTTPServer(("127.0.0.1", 0), _handler(self))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def answer(self, method: str, result: Any) -> None:
        """Makes a method return this result. A list is consumed one call at a time."""
        self.replies[method] = result

    def fail(self, method: str, code: int, message: str, data: Any = None) -> None:
        """Makes a method return a JSON-RPC error object."""
        self.errors[method] = {"code": code, "message": message, "data": data}

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _handler(fake: FakeServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": open\n\n")
            for frame in fake.events:
                self.wfile.write(f"data: {frame}\n\n".encode())
            self.wfile.flush()

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length))
            method = request.get("method")
            fake.calls.append((method, request.get("params")))

            if method in fake.errors:
                body = {"jsonrpc": "2.0", "id": request.get("id"), "error": fake.errors[method]}
            elif method in fake.replies:
                result = fake.replies[method]
                if isinstance(result, list) and result and isinstance(result[0], _Once):
                    result = result.pop(0).value
                body = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
            else:
                body = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32601, "message": f"No such method: {method}"},
                }
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


class _Once:
    """One reply in a sequence."""

    def __init__(self, value: Any) -> None:
        self.value = value


def once(*values: Any) -> list[_Once]:
    """Builds a sequence of replies, returned one per call."""
    return [_Once(value) for value in values]


@pytest.fixture
def fake() -> FakeServer:
    server = FakeServer()
    yield server
    server.close()
