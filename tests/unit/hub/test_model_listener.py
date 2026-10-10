# -*- coding: utf-8 -*-
"""Model listeners bind only explicitly selected host interfaces."""
# pylint: disable=protected-access

import socket
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from qwenpaw.hub.model_service.listener import ModelListener
from qwenpaw.hub.model_service.storage import GovernanceStore
from qwenpaw.hub.provisioner import RuntimeModelNetwork


def _listener(tmp_path: Path) -> ModelListener:
    return ModelListener(GovernanceStore(tmp_path / "hub.db"), None, None)


def test_model_network_requires_started_listener() -> None:
    network = RuntimeModelNetwork("127.0.0.1", "127.0.0.1")
    with pytest.raises(RuntimeError, match="not running"):
        network.url(0)


async def test_no_available_backend_opens_no_listener(tmp_path: Path) -> None:
    listener = _listener(tmp_path)
    with patch.object(listener, "_bind") as bind:
        async with listener.serve(set()):
            assert listener.port == 0
        bind.assert_not_called()


def test_loopback_listener_reuses_persisted_port(tmp_path: Path) -> None:
    listener = _listener(tmp_path)
    sockets = listener._bind(["127.0.0.1"])
    try:
        port = listener.port
        assert sockets[0].getsockname() == ("127.0.0.1", port)
        assert port > 0
    finally:
        for bound in sockets:
            bound.close()
    sockets = listener._bind(["127.0.0.1"])
    try:
        assert sockets[0].getsockname() == ("127.0.0.1", port)
    finally:
        for bound in sockets:
            bound.close()


def test_loopback_and_bridge_share_one_port(tmp_path: Path) -> None:
    listener = _listener(tmp_path)
    loopback, bridge = Mock(), Mock()
    loopback.getsockname.return_value = ("127.0.0.1", 43123)
    bridge.getsockname.return_value = ("172.17.0.1", 43123)
    with patch.object(socket, "socket", side_effect=[loopback, bridge]):
        sockets = listener._bind(["127.0.0.1", "172.17.0.1"])
    assert sockets == [loopback, bridge]
    loopback.bind.assert_called_once_with(("127.0.0.1", 0))
    bridge.bind.assert_called_once_with(("172.17.0.1", 43123))
    assert listener.port == 43123


def test_unavailable_bridge_closes_sockets_without_fallback(
    tmp_path: Path,
) -> None:
    listener = _listener(tmp_path)
    loopback, bridge = Mock(), Mock()
    loopback.getsockname.return_value = ("127.0.0.1", 43123)
    bridge.bind.side_effect = OSError("address unavailable")
    with (
        patch.object(socket, "socket", side_effect=[loopback, bridge]),
        pytest.raises(OSError, match="address unavailable"),
    ):
        listener._bind(["127.0.0.1", "172.17.0.1"])
    loopback.close.assert_called_once()
    bridge.close.assert_called_once()
    assert listener.port == 0
    with listener.store.connect() as db:
        assert (
            db.execute(
                "SELECT 1 FROM hub_settings WHERE key = 'model_listener_port'",
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "8.8.8.8", "224.0.0.1"],
)
def test_model_listener_rejects_unsafe_addresses(
    tmp_path: Path,
    host: str,
) -> None:
    listener = _listener(tmp_path)
    with patch.object(socket, "socket") as create_socket:
        with pytest.raises(ValueError):
            listener._bind([host])
        create_socket.assert_not_called()
