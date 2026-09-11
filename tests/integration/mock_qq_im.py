# -*- coding: utf-8 -*-
"""Minimal mock QQ IM backend for integration tests.

Hosts, in the *test* process, the three external surfaces the QQ
channel needs, so the real qwenpaw app subprocess can run its QQ
channel end-to-end without touching qq.com:

* ``POST /app/getAppAccessToken``  -> fake token (QQ_TOKEN_URL)
* ``GET  /gateway``                -> ws:// URL of the mock WS server
  (QQ_API_BASE)
* ``POST /v2/users/.../messages`` etc. -> recorded, 200 {"id": ...}

WebSocket side implements just enough of the QQ bot gateway protocol:
HELLO -> (client IDENTIFY) -> READY, replies HEARTBEAT_ACK, and lets
tests push DISPATCH events (e.g. C2C_MESSAGE_CREATE) to the connected
channel.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handlers touch own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

MOCK_TOKEN = "integ-mock-qq-token"


class MockQQIM:
    """Mock QQ IM backend (HTTP API + WS gateway) on localhost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self.ws_port: int = 0
        # Recorded outbound API calls: dicts with method/path/body/auth.
        self.api_calls: list[dict[str, Any]] = []
        # Latest connected WS session (one at a time is enough).
        self._ws_conn: Optional[Any] = None
        self._identified = threading.Event()
        self._seq = 0
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._ws_server: Optional[Any] = None

    # -------------------------------------------------------------- #
    # lifecycle
    # -------------------------------------------------------------- #

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_http()
        self._start_ws()

    @property
    def token_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}/app/getAppAccessToken"

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    # -------------------------------------------------------------- #
    # HTTP API (token + gateway + message sinks)
    # -------------------------------------------------------------- #

    def _start_http(self) -> None:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, code: int, obj: dict) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {}
                if self.path == "/app/getAppAccessToken":
                    self._json(
                        200,
                        {"access_token": MOCK_TOKEN, "expires_in": 7200},
                    )
                    return
                with mock._lock:
                    mock.api_calls.append(
                        {
                            "method": "POST",
                            "path": self.path,
                            "body": body,
                            "auth": self.headers.get("Authorization", ""),
                        },
                    )
                self._json(200, {"id": f"mock-msg-{len(mock.api_calls)}"})

            def do_GET(self) -> None:
                if self.path == "/gateway":
                    self._json(
                        200,
                        {"url": f"ws://127.0.0.1:{mock.ws_port}"},
                    )
                    return
                with mock._lock:
                    mock.api_calls.append(
                        {
                            "method": "GET",
                            "path": self.path,
                            "body": {},
                            "auth": self.headers.get("Authorization", ""),
                        },
                    )
                self._json(200, {})

            def do_PUT(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {}
                with mock._lock:
                    mock.api_calls.append(
                        {
                            "method": "PUT",
                            "path": self.path,
                            "body": body,
                            "auth": self.headers.get("Authorization", ""),
                        },
                    )
                self._json(200, {})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-qq-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # WS gateway
    # -------------------------------------------------------------- #

    def _start_ws(self) -> None:
        mock = self

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn
            hello = {"op": OP_HELLO, "d": {"heartbeat_interval": 45000}}
            conn.send(json.dumps(hello))
            try:
                for raw in conn:
                    try:
                        payload = json.loads(raw)
                    except ValueError:
                        continue
                    op = payload.get("op")
                    if op == OP_IDENTIFY:
                        ready = {
                            "op": OP_DISPATCH,
                            "s": mock._next_seq(),
                            "t": "READY",
                            "d": {"session_id": "mock-session-1"},
                        }
                        conn.send(json.dumps(ready))
                        mock._identified.set()
                    elif op == OP_HEARTBEAT:
                        conn.send(json.dumps({"op": OP_HEARTBEAT_ACK}))
            except Exception:  # noqa: BLE001 - client dropped; fine
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
            name="mock-qq-ws",
            daemon=True,
        ).start()

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def wait_identified(self, timeout: float = 30.0) -> bool:
        """Block until the channel completed HELLO->IDENTIFY->READY."""
        return self._identified.wait(timeout)

    def reset_identified(self) -> None:
        """Clear the IDENTIFY flag before triggering a channel reload."""
        self._identified.clear()

    def push_dispatch(self, event_type: str, d: dict) -> None:
        """Push an arbitrary DISPATCH event to the connected channel."""
        event = {
            "op": OP_DISPATCH,
            "s": self._next_seq(),
            "t": event_type,
            "d": d,
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no WS client connected"
        conn.send(json.dumps(event))

    def push_c2c_message(
        self,
        *,
        openid: str,
        text: str,
        msg_id: str = "mock-incoming-1",
    ) -> None:
        """Push a C2C_MESSAGE_CREATE dispatch to the connected channel."""
        self.push_dispatch(
            "C2C_MESSAGE_CREATE",
            {
                "id": msg_id,
                "content": text,
                "author": {"user_openid": openid},
            },
        )

    def sent_texts(self, path_prefix: str = "/v2/users/") -> list[str]:
        """Texts of recorded outbound messages under *path_prefix*."""
        out: list[str] = []
        with self._lock:
            calls = list(self.api_calls)
        for call in calls:
            if not call["path"].startswith(path_prefix):
                continue
            body = call.get("body") or {}
            text = body.get("content") or (body.get("markdown") or {}).get(
                "content",
            )
            if text:
                out.append(str(text))
        return out

    def wait_for_sent_text(
        self,
        predicate,
        *,
        timeout: float = 60.0,
        path_prefix: str = "/v2/users/",
    ) -> Optional[str]:
        """Poll recorded sends until *predicate(text)* matches."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.sent_texts(path_prefix):
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
