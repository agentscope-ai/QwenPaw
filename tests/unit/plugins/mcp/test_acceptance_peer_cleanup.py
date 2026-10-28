# -*- coding: utf-8 -*-
"""Acceptance peer owns startup failures and bounded process shutdown."""
# pytest injects the probe fixture by its declared name.
# pylint: disable=redefined-outer-name

import importlib.util
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

PROBE = (
    Path(__file__).resolve().parents[3]
    / "fixtures/mcp/optional_runtime_probe.py"
)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(PROBE), "auth-oauth", str(tmp_path)])
    spec = importlib.util.spec_from_file_location(
        "acceptance_probe_cleanup",
        PROBE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = Mock()
    connection.getsockname.return_value = ("127.0.0.1", 42424)
    socket_context = Mock()
    socket_context.__enter__ = Mock(return_value=connection)
    socket_context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        module,
        "socket",
        SimpleNamespace(socket=Mock(return_value=socket_context)),
    )
    return module


@pytest.mark.parametrize("failure", ["readiness", "preparation"])
async def test_auth_peer_cleanup_owns_start_and_preparation_failure(
    probe,
    monkeypatch,
    failure,
):
    peers = []
    original = probe.LocalPeer

    class Peer(original):
        async def start(self):
            self.process = Mock()
            self.process.poll.return_value = None
            peers.append(self)
            if failure == "readiness":
                raise RuntimeError("synthetic readiness failure")

    def fail_seed(**_kwargs):
        raise RuntimeError("synthetic preparation failure")

    monkeypatch.setattr(probe, "LocalPeer", Peer)
    monkeypatch.setattr(probe, "seed", fail_seed)
    with pytest.raises(RuntimeError, match="synthetic"):
        await probe.auth_oauth()
    assert len(peers) == 1
    peers[0].process.terminate.assert_called_once()
    peers[0].process.wait.assert_called_once()
    assert peers[0].log.closed


def test_peer_terminate_timeout_kills_waits_and_closes_log(probe):
    peer = probe.LocalPeer("sse")
    process = Mock()
    peer.process = process
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired("synthetic-peer", 10),
        0,
    ]
    peer.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert all(
        call.kwargs.get("timeout", 0) > 0
        for call in process.wait.call_args_list
    )
    assert peer.log.closed


def test_peer_log_closes_even_if_shutdown_fails(probe):
    peer = probe.LocalPeer("sse")
    peer.process = Mock()
    peer.process.poll.return_value = None
    peer.process.terminate.side_effect = OSError("synthetic terminate failure")
    with pytest.raises(OSError, match="synthetic"):
        peer.close()
    assert peer.log.closed
