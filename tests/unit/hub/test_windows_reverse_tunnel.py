# -*- coding: utf-8 -*-
"""Tests for the Windows AppContainer reverse TCP tunnel."""

from __future__ import annotations

import socket
import threading
import time

from qwenpaw.hub.windows_reverse_tunnel import (
    WindowsReverseTunnelBroker,
    run_reverse_tunnel_client,
)


def _echo_once(listener: socket.socket) -> None:
    connection, _ = listener.accept()
    with connection:
        payload = connection.recv(1024)
        connection.sendall(payload)


def test_reverse_tunnel_relays_runtime_traffic() -> None:
    target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    target.bind(("127.0.0.1", 0))
    target.listen(1)
    target_port = int(target.getsockname()[1])
    target_thread = threading.Thread(
        target=_echo_once,
        args=(target,),
        daemon=True,
    )
    target_thread.start()

    broker = WindowsReverseTunnelBroker("127.0.0.1", 0)
    broker.start()
    stop_event = threading.Event()
    client_thread = threading.Thread(
        target=run_reverse_tunnel_client,
        args=(
            broker.control_port,
            broker.token,
            target_port,
            stop_event,
        ),
        daemon=True,
    )
    client_thread.start()

    response = b""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not response:
        try:
            with socket.create_connection(
                (broker.host, broker.port),
                timeout=1,
            ) as connection:
                connection.sendall(b"hub-runtime-round-trip")
                response = connection.recv(1024)
        except OSError:
            time.sleep(0.05)

    stop_event.set()
    broker.close()
    target.close()
    client_thread.join(timeout=2)
    target_thread.join(timeout=2)

    assert response == b"hub-runtime-round-trip"
