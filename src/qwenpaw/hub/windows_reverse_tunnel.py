# -*- coding: utf-8 -*-
"""Reverse TCP tunnel used by Windows AppContainer Hub runtimes."""

from __future__ import annotations

import secrets
import selectors
import socket
import threading
import time
import uuid
from collections.abc import Callable

_HANDSHAKE_LIMIT = 1024
_CONNECT_TIMEOUT_SECONDS = 10.0


def _read_line(connection: socket.socket) -> str:
    payload = bytearray()
    while len(payload) < _HANDSHAKE_LIMIT:
        chunk = connection.recv(1)
        if not chunk:
            break
        if chunk == b"\n":
            return payload.decode("ascii")
        payload.extend(chunk)
    raise OSError("Invalid Windows runtime tunnel handshake")


def _relay(left: socket.socket, right: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    try:
        selector.register(left, selectors.EVENT_READ)
        selector.register(right, selectors.EVENT_READ)
        while True:
            for key, _ in selector.select(timeout=1):
                source = left if key.fileobj is left else right
                target = right if source is left else left
                payload = source.recv(65536)
                if not payload:
                    return
                target.sendall(payload)
    except OSError:
        return
    finally:
        selector.close()
        left.close()
        right.close()


class WindowsReverseTunnelBroker:
    """Expose a loopback TCP port through outbound AppContainer sockets."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.control_port = 0
        self.token = secrets.token_urlsafe(32)
        self._public_listener: socket.socket | None = None
        self._control_listener: socket.socket | None = None
        self._control: socket.socket | None = None
        self._pending: dict[str, tuple[socket.socket, float]] = {}
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Bind host listeners and start connection pairing threads."""
        self._public_listener = self._listener(self.host, self.port)
        self.port = int(self._public_listener.getsockname()[1])
        self._control_listener = self._listener("127.0.0.1", 0)
        self.control_port = int(self._control_listener.getsockname()[1])
        self._start_thread(self._accept_public, "qwenpaw-tunnel-public")
        self._start_thread(self._accept_control, "qwenpaw-tunnel-control")

    def close(self) -> None:
        """Close listeners, the control channel, and pending clients."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        with self._lock:
            sockets = [
                self._public_listener,
                self._control_listener,
                self._control,
                *(item[0] for item in self._pending.values()),
            ]
            self._pending.clear()
            self._control = None
        for connection in sockets:
            if connection is not None:
                connection.close()
        for thread in self._threads:
            thread.join(timeout=2)

    @staticmethod
    def _listener(host: str, port: int) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(128)
        listener.settimeout(0.5)
        return listener

    def _start_thread(
        self,
        target: Callable[[], None],
        name: str,
    ) -> None:
        thread = threading.Thread(
            target=target,
            name=name,
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)

    def _accept_public(self) -> None:
        assert self._public_listener is not None
        while not self._stopped.is_set():
            self._expire_pending()
            try:
                client, _ = self._public_listener.accept()
            except (OSError, socket.timeout):
                continue
            connection_id = uuid.uuid4().hex
            with self._lock:
                control = self._control
                if control is None:
                    client.close()
                    continue
                self._pending[connection_id] = (
                    client,
                    time.monotonic() + _CONNECT_TIMEOUT_SECONDS,
                )
                try:
                    control.sendall(f"OPEN {connection_id}\n".encode("ascii"))
                except OSError:
                    if connection_id in self._pending:
                        del self._pending[connection_id]
                    self._control = None
                    client.close()

    def _accept_control(self) -> None:
        assert self._control_listener is not None
        while not self._stopped.is_set():
            self._expire_pending()
            connection: socket.socket | None = None
            try:
                connection, _ = self._control_listener.accept()
                connection.settimeout(_CONNECT_TIMEOUT_SECONDS)
                handshake = _read_line(connection).split(" ", 2)
                connection.settimeout(None)
                self._handle_tunnel_connection(connection, handshake)
            except (OSError, socket.timeout, UnicodeError):
                if connection is not None:
                    connection.close()
                continue

    def _handle_tunnel_connection(
        self,
        connection: socket.socket,
        handshake: list[str],
    ) -> None:
        if len(handshake) < 2 or handshake[1] != self.token:
            connection.close()
            return
        if handshake[0] == "CONTROL" and len(handshake) == 2:
            with self._lock:
                previous = self._control
                self._control = connection
                pending = [item[0] for item in self._pending.values()]
                self._pending.clear()
            if previous is not None:
                previous.close()
            for client in pending:
                client.close()
            return
        if handshake[0] != "DATA" or len(handshake) != 3:
            connection.close()
            return
        with self._lock:
            pending = self._pending.get(handshake[2])
            if pending is not None:
                del self._pending[handshake[2]]
        if pending is None:
            connection.close()
            return
        client = pending[0]
        self._start_thread(
            lambda: _relay(client, connection),
            f"qwenpaw-tunnel-{handshake[2][:8]}",
        )

    def _expire_pending(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                connection_id
                for connection_id, (_, deadline) in self._pending.items()
                if deadline <= now
            ]
            clients = [
                self._pending.pop(connection_id)[0]
                for connection_id in expired
            ]
        for client in clients:
            client.close()


def run_reverse_tunnel_client(
    control_port: int,
    token: str,
    target_port: int,
    stop_event: threading.Event,
) -> None:
    """Connect an AppContainer runtime to its full-trust host broker."""
    while not stop_event.is_set():
        try:
            with socket.create_connection(
                ("127.0.0.1", control_port),
                timeout=2,
            ) as control:
                control.settimeout(None)
                control.sendall(f"CONTROL {token}\n".encode("ascii"))
                with control.makefile("r", encoding="ascii") as control_file:
                    for line in control_file:
                        if stop_event.is_set():
                            return
                        command = line.strip().split(" ", 1)
                        if len(command) == 2 and command[0] == "OPEN":
                            threading.Thread(
                                target=_open_data_tunnel,
                                args=(
                                    control_port,
                                    token,
                                    command[1],
                                    target_port,
                                ),
                                daemon=True,
                            ).start()
        except OSError:
            if stop_event.wait(0.1):
                return


def _open_data_tunnel(
    control_port: int,
    token: str,
    connection_id: str,
    target_port: int,
) -> None:
    deadline = time.monotonic() + _CONNECT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        host: socket.socket | None = None
        target: socket.socket | None = None
        try:
            host = socket.create_connection(
                ("127.0.0.1", control_port),
                timeout=2,
            )
            target = socket.create_connection(
                ("127.0.0.1", target_port),
                timeout=2,
            )
            host.settimeout(None)
            target.settimeout(None)
            host.sendall(
                f"DATA {token} {connection_id}\n".encode("ascii"),
            )
            _relay(host, target)
            return
        except OSError:
            if host is not None:
                host.close()
            if target is not None:
                target.close()
            time.sleep(0.1)
