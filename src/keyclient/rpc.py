"""The wire layer: JSON-RPC 2.0 over HTTP, and nothing else.

There is deliberately no retrying and no reconnecting anywhere in this file. A proof is stateful,
and a request that may have been applied once must not be applied again because a socket
hiccupped: silently replaying ``goal.applyScript`` would change a proof twice and leave the caller
believing it changed once. If the connection breaks, this raises and the caller decides.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from itertools import count
from typing import Any

from .exceptions import KeyClientError, KeyServerRpcError

__all__ = ["RpcTransport"]


class RpcTransport:
    """Sends JSON-RPC requests to one server."""

    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.url = f"http://{host}:{port}/rpc"
        self._ids = count(1)

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Calls a method and returns its result.

        :param method: the ``namespace.verb`` name
        :param params: named parameters; the protocol accepts no positional ones
        :returns: the ``result`` member of the response
        :raises KeyServerRpcError: when the server answers with an error object
        :raises KeyClientError: when the server cannot be reached or answers nonsense
        """
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
        }
        if params is not None:
            request["params"] = params

        body = json.dumps(request).encode("utf-8")
        http = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise KeyClientError(
                f"{method} was refused with HTTP {error.code} by {self.url}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise KeyClientError(
                f"Could not reach the KeY server at {self.url}: {error}"
            ) from error

        if not raw:
            raise KeyClientError(f"{method} returned an empty body")
        try:
            response_object = json.loads(raw)
        except json.JSONDecodeError as error:
            raise KeyClientError(
                f"{method} returned a body that is not JSON: {raw[:200]}"
            ) from error

        if "error" in response_object:
            failure = response_object["error"]
            raise KeyServerRpcError(
                int(failure.get("code", 0)),
                str(failure.get("message", "")),
                failure.get("data"),
            )
        return response_object.get("result")
