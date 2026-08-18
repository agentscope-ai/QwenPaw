# -*- coding: utf-8 -*-
"""Minimal mock Mattermost server for integration tests.

The Mattermost channel uses one ``url`` for everything: REST under
``/api/v4/...`` (httpx) and WebSocket at ``/api/v4/websocket``
(plain ``websockets.connect``, ws:// works). This mock hosts both:

* ``GET /api/v4/users/me``  -> bot identity
* ``POST /api/v4/posts``    -> recorded outbound reply
* other REST               -> benign 200
* WS: accepts the authentication_challenge, lets tests push
  ``posted`` events.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handlers touch own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve

BOT_USER_ID = "integmockbotid00000000000"
BOT_USERNAME = "integ-mock-bot"


class MockMattermost:
    """Mock Mattermost backend (REST + WS) on localhost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self.ws_port: int = 0
        self.posts: list[dict[str, Any]] = []
        self._ws_conn: Optional[Any] = None
        self._connected = threading.Event()
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._ws_server: Optional[Any] = None
        self._post_counter = 0

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_ws()
        self._start_http()

    @property
    def url(self) -> str:
        """Value for the Mattermost channel ``url`` config field.

        Points at the HTTP server, which serves REST directly and
        byte-proxies ``/api/v4/websocket`` upgrades to the internal WS
        server — so REST and WS share one base URL like a real
        Mattermost instance.
        """
        return f"http://127.0.0.1:{self.http_port}"

    # -------------------------------------------------------------- #
    # HTTP (REST + WS proxy)
    # -------------------------------------------------------------- #

    # pylint: disable-next=too-many-statements
    def _start_http(self) -> None:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, obj: Any, code: int = 200) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    return json.loads(raw) if raw else {}
                except ValueError:
                    return {}

            def do_GET(self) -> None:
                if self.path == "/api/v4/websocket":
                    self._proxy_ws()
                    return
                if self.path == "/api/v4/users/me":
                    self._json(
                        {
                            "id": BOT_USER_ID,
                            "username": BOT_USERNAME,
                            "first_name": "Integ",
                            "last_name": "Bot",
                        },
                    )
                    return
                self._json({})

            def do_POST(self) -> None:
                body = self._read_body()
                if self.path == "/api/v4/posts":
                    with mock._lock:
                        mock.posts.append(body)
                        mock._post_counter += 1
                        n = mock._post_counter
                    self._json(
                        {
                            "id": f"mockpost{n:016d}",
                            "channel_id": body.get("channel_id", ""),
                            "message": body.get("message", ""),
                            "root_id": body.get("root_id", ""),
                        },
                        code=201,
                    )
                    return
                self._json({})

            def _proxy_ws(self) -> None:
                """Byte-proxy the WS upgrade to the real WS server."""
                import socket

                upstream = socket.create_connection(
                    ("127.0.0.1", mock.ws_port),
                )
                # Replay the request line + headers we already read.
                lines = [f"GET {self.path} HTTP/1.1"]
                for key, value in self.headers.items():
                    lines.append(f"{key}: {value}")
                payload = ("\r\n".join(lines) + "\r\n\r\n").encode()
                upstream.sendall(payload)

                client = self.connection
                client.setblocking(True)
                upstream.setblocking(True)

                import selectors

                sel = selectors.DefaultSelector()
                sel.register(client, selectors.EVENT_READ, "client")
                sel.register(upstream, selectors.EVENT_READ, "upstream")
                try:
                    while True:
                        for key, _ in sel.select(timeout=60):
                            src = key.fileobj
                            dst = upstream if key.data == "client" else client
                            data = src.recv(65536)
                            if not data:
                                return
                            dst.sendall(data)
                except Exception:  # noqa: BLE001 - either side closed
                    pass
                finally:
                    sel.close()
                    try:
                        upstream.close()
                    except Exception:  # noqa: BLE001
                        pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-mattermost-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # WS
    # -------------------------------------------------------------- #

    def _start_ws(self) -> None:
        mock = self

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn
            try:
                for raw in conn:
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    if data.get("action") == "authentication_challenge":
                        conn.send(
                            json.dumps(
                                {
                                    "status": "OK",
                                    "seq_reply": data.get("seq", 1),
                                },
                            ),
                        )
                        mock._connected.set()
            except Exception:  # noqa: BLE001 - client dropped
                pass
            finally:
                with mock._lock:
                    if mock._ws_conn is conn:
                        mock._ws_conn = None

        server = ws_serve(handler, "127.0.0.1", 0)
        self.ws_port = server.socket.getsockname()[1]
        self._ws_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-mattermost-ws",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def wait_connected(self, timeout: float = 60.0) -> bool:
        return self._connected.wait(timeout)

    def reset_connected(self) -> None:
        self._connected.clear()

    @property
    def has_connection(self) -> bool:
        with self._lock:
            return self._ws_conn is not None

    def push_dm_post(
        self,
        *,
        text: str,
        channel_id: str = "integmockdmchannel000000",
        user_id: str = "integmockuser00000000000",
        post_id: str = "",
    ) -> str:
        """Push a 'posted' DM event to the connected channel."""
        with self._lock:
            self._post_counter += 1
            n = self._post_counter
        pid = post_id or f"incoming{n:016d}"
        post = {
            "id": pid,
            "user_id": user_id,
            "channel_id": channel_id,
            "message": text,
            "root_id": "",
            "create_at": int(time.time() * 1000),
        }
        event = {
            "event": "posted",
            "seq": n,
            "data": {
                "post": json.dumps(post),
                "channel_type": "D",
                "sender_name": "@integ-user",
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no mattermost client connected"
        conn.send(json.dumps(event))
        return pid

    def push_channel_post(
        self,
        *,
        text: str,
        channel_id: str = "integmockopenchannel0000",
        user_id: str = "integmockuser00000000000",
        post_id: str = "",
        root_id: str = "",
    ) -> str:
        """Push a 'posted' open-channel event (channel_type=O)."""
        with self._lock:
            self._post_counter += 1
            n = self._post_counter
        pid = post_id or f"incomingo{n:015d}"
        post = {
            "id": pid,
            "user_id": user_id,
            "channel_id": channel_id,
            "message": text,
            "root_id": root_id,
            "create_at": int(time.time() * 1000),
        }
        event = {
            "event": "posted",
            "seq": n,
            "data": {
                "post": json.dumps(post),
                "channel_type": "O",
                "sender_name": "@integ-user",
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no mattermost client connected"
        conn.send(json.dumps(event))
        return pid

    def replied_messages(self) -> list[str]:
        with self._lock:
            posts = list(self.posts)
        return [str(p.get("message", "")) for p in posts if p.get("message")]

    def wait_for_reply(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.replied_messages():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
