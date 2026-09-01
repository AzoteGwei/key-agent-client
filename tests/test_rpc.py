"""The wire layer, and what it refuses to do."""

from __future__ import annotations

import pytest
from conftest import FakeServer

from keyclient.exceptions import ErrorCode, KeyClientError, KeyServerRpcError
from keyclient.rpc import RpcTransport


def test_a_result_comes_back_as_it_was_sent(fake: FakeServer) -> None:
    fake.answer("server.version", {"apiVersion": "0.1.0", "instanceId": "inst-1"})

    result = RpcTransport("127.0.0.1", fake.port).call("server.version")

    assert result == {"apiVersion": "0.1.0", "instanceId": "inst-1"}
    assert fake.calls == [("server.version", None)]


def test_an_error_object_becomes_an_exception_carrying_its_code(fake: FakeServer) -> None:
    fake.fail(
        "environment.load",
        ErrorCode.LOAD_FAILED,
        "No such file",
        {"positions": [{"file": "a.key", "line": 7, "column": 1, "message": "boom"}]},
    )

    with pytest.raises(KeyServerRpcError) as raised:
        RpcTransport("127.0.0.1", fake.port).call("environment.load", {"path": "x"})

    # Callers branch on the number. The text is for people and is allowed to change.
    assert raised.value.code == ErrorCode.LOAD_FAILED
    assert raised.value.positions[0]["line"] == 7


def test_an_unreachable_server_raises_instead_of_retrying() -> None:
    # Nothing is listening. A retry loop here would be worse than useless: a request that may
    # already have changed a proof must never be sent twice on its own.
    transport = RpcTransport("127.0.0.1", 1, timeout=0.5)

    with pytest.raises(KeyClientError) as raised:
        transport.call("server.health")

    assert "Could not reach" in str(raised.value)
