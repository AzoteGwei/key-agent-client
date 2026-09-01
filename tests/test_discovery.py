"""Finding a server, and the message when there is none."""

from __future__ import annotations

import json
import os

import pytest

from keyclient.discovery import list_instances, resolve
from keyclient.exceptions import InstanceNotFoundError


def _record(directory, instance_id: str, pid: int, port: int = 8899, workspace: str = "/ws"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{instance_id}.json").write_text(
        json.dumps(
            {
                "instanceId": instance_id,
                "pid": pid,
                "host": "127.0.0.1",
                "port": port,
                "workspacePath": workspace,
                "apiVersion": "0.1.0",
                "keyVersion": "3.1.0-dev",
                "threads": 1,
                "startedAt": f"2026-09-01T0{pid % 10}:00:00Z",
            }
        )
    )


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(directory))
    return directory / "keyext-server" / "instances"


def test_a_record_whose_process_is_gone_is_reported_as_stale(state) -> None:
    _record(state, "inst-live", os.getpid())
    _record(state, "inst-dead", 0)

    found = {each.instance_id: each for each in list_instances()}

    assert found["inst-live"].alive is True
    assert found["inst-live"].stale is False
    assert found["inst-dead"].stale is True


def test_resolve_ignores_stale_records(state) -> None:
    _record(state, "inst-dead", 0, port=1111)
    _record(state, "inst-live", os.getpid(), port=2222)

    assert resolve().instance_id == "inst-live"


def test_resolve_says_how_to_start_one_when_there_is_none(state, tmp_path) -> None:
    with pytest.raises(InstanceNotFoundError) as raised:
        resolve(workspace=tmp_path)

    message = str(raised.value)
    # The most likely reader is an agent, and an agent that is handed a command can fix this
    # itself. A message that only said "not found" would leave it stuck.
    assert "java -jar" in message
    assert "--workspace" in message
    assert str(tmp_path) in message


def test_a_broken_record_costs_only_itself(state) -> None:
    _record(state, "inst-good", os.getpid())
    state.mkdir(parents=True, exist_ok=True)
    (state / "inst-garbage.json").write_text("{ not json")

    found = list_instances()

    assert [each.instance_id for each in found] == ["inst-good"]


def test_an_absent_registry_is_an_empty_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "nothing-here"))

    assert list_instances() == []
