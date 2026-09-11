# -*- coding: utf-8 -*-
"""Minimal mock Feishu (Lark) backend for integration tests.

Serves the surfaces the Feishu channel touches when its ``domain``
config field carries a custom http(s) base URL:

* ``POST /callback/ws/endpoint`` -> ws:// URL of the mock WS gateway
  (lark_oapi ws.Client's endpoint discovery).
* ``GET /open-apis/bot/v3/info`` -> bot open_id (fetched at startup).
* ``POST /open-apis/im/v1/messages`` -> outbound reply sink (the
  lark.Client message create API).
* ``POST /open-apis/auth/v3/tenant_access_token/internal`` -> token.

WS gateway speaks the lark protobuf frame protocol: on connect it just
accepts; tests push DATA frames whose payload is a p2
``im.message.receive_v1`` event, which the SDK dispatches to the
channel's registered handler.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handlers touch own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve


def _build_event_frame(payload: dict) -> bytes:
    """Serialize a lark DATA frame carrying *payload* as an EVENT."""
    # tests/conftest.py stubs lark_oapi with a MagicMock for unit
    # tests; drop the stub so the real installed SDK is imported here.
    import sys
    from unittest.mock import MagicMock

    if isinstance(sys.modules.get("lark_oapi"), MagicMock):
        for name in [
            key
            for key in sys.modules
            if key == "lark_oapi" or key.startswith("lark_oapi.")
        ]:
            del sys.modules[name]

    from lark_oapi.ws import const as c
    from lark_oapi.ws.enum import FrameType
    from lark_oapi.ws.pb.pbbp2_pb2 import Frame

    frame = Frame()
    frame.SeqID = 0
    frame.LogID = 0
    frame.service = 1
    frame.method = FrameType.DATA.value
    raw = json.dumps(payload).encode()
    for key, value in (
        (c.HEADER_TYPE, "event"),
        (c.HEADER_MESSAGE_ID, f"mock-{int(time.time() * 1000)}"),
        (c.HEADER_TRACE_ID, "mock-trace"),
        (c.HEADER_SUM, "1"),
        (c.HEADER_SEQ, "0"),
    ):
        header = frame.headers.add()
        header.key = key
        header.value = value
    frame.payload = raw
    return frame.SerializeToString()


class MockFeishuIM:
    """Mock Feishu backend (endpoint discovery + WS + API sinks)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self.ws_port: int = 0
        # Recorded outbound API calls (message sends etc.).
        self.api_calls: list[dict[str, Any]] = []
        self._ws_conn: Optional[Any] = None
        self._connected = threading.Event()
        self._msg_counter = 0
        self._http_server: Optional[ThreadingHTTPServer] = None
        self._ws_server: Optional[Any] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_http()
        self._start_ws()

    @property
    def base_url(self) -> str:
        """Value for the Feishu channel ``domain`` config field."""
        return f"http://127.0.0.1:{self.http_port}"

    # -------------------------------------------------------------- #
    # HTTP
    # -------------------------------------------------------------- #

    def _start_http(self) -> None:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, obj: dict, code: int = 200) -> None:
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

            def do_POST(self) -> None:
                body = self._read_body()
                if self.path == "/callback/ws/endpoint":
                    self._json(
                        {
                            "code": 0,
                            "msg": "ok",
                            "data": {
                                "URL": (
                                    f"ws://127.0.0.1:{mock.ws_port}/ws"
                                    "?device_id=integ-dev-1"
                                    "&service_id=1"
                                ),
                                "ClientConfig": {
                                    "ReconnectCount": 3,
                                    "ReconnectInterval": 1,
                                    "ReconnectNonce": 1,
                                    "PingInterval": 30,
                                },
                            },
                        },
                    )
                    return
                if "tenant_access_token" in self.path:
                    self._json(
                        {
                            "code": 0,
                            "msg": "ok",
                            "tenant_access_token": "integ-mock-lark-token",
                            "expire": 7200,
                        },
                    )
                    return
                with mock._lock:
                    mock.api_calls.append(
                        {
                            "method": "POST",
                            "path": self.path,
                            "body": body,
                        },
                    )
                    mock._msg_counter += 1
                    n = mock._msg_counter
                self._json(
                    {
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "message_id": f"om_mock_{n}",
                            "chat_id": "oc_mock_chat",
                        },
                    },
                )

            def do_GET(self) -> None:
                if self.path.startswith("/open-apis/bot/v3/info"):
                    self._json(
                        {
                            "code": 0,
                            "msg": "ok",
                            "bot": {
                                "open_id": "ou_integ_mock_bot",
                                "app_name": "Integ Mock Bot",
                            },
                        },
                    )
                    return
                with mock._lock:
                    mock.api_calls.append(
                        {"method": "GET", "path": self.path, "body": {}},
                    )
                self._json({"code": 0, "msg": "ok", "data": {}})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-feishu-http",
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
            mock._connected.set()
            try:
                for _raw in conn:
                    # SDK sends response/ack frames; ignore.
                    pass
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
            name="mock-feishu-ws",
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

    def push_p2_text_message(
        self,
        *,
        text: str,
        sender_open_id: str = "ou_integ_sender",
        chat_id: str = "oc_integ_chat",
        chat_type: str = "p2p",
        message_id: str = "",
        mention_bot: bool = False,
    ) -> str:
        """Push a p2 im.message.receive_v1 text event over the WS.

        ``mention_bot`` attaches a mentions entry targeting the mock
        bot's open_id (ou_integ_mock_bot), which group chats need.
        """
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = message_id or f"om_integ_incoming_{n}"
        event = {
            "schema": "2.0",
            "header": {
                "event_id": f"evt-{mid}",
                "event_type": "im.message.receive_v1",
                "create_time": str(int(time.time() * 1000)),
                "token": "integ-mock-verification",
                "app_id": "cli_integ_mock",
                "tenant_key": "integ_tenant",
            },
            "event": {
                "sender": {
                    "sender_id": {
                        "open_id": sender_open_id,
                        "user_id": "u_integ",
                        "union_id": "on_integ",
                    },
                    "sender_type": "user",
                    "tenant_key": "integ_tenant",
                },
                "message": {
                    "message_id": mid,
                    "create_time": str(int(time.time() * 1000)),
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "message_type": "text",
                    "content": json.dumps(
                        {
                            "text": ("@_user_1 " + text)
                            if mention_bot
                            else text,
                        },
                    ),
                    **(
                        {
                            "mentions": [
                                {
                                    "key": "@_user_1",
                                    "id": {
                                        "open_id": "ou_integ_mock_bot",
                                        "user_id": "bot",
                                        "union_id": "on_bot",
                                    },
                                    "name": "Integ Mock Bot",
                                    "tenant_key": "integ_tenant",
                                },
                            ],
                        }
                        if mention_bot
                        else {}
                    ),
                },
            },
        }
        frame_bytes = _build_event_frame(event)
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no lark SDK client connected"
        conn.send(frame_bytes)
        return mid

    def push_p2_image_message(
        self,
        *,
        image_key: str = "img_integ_key_1",
        sender_open_id: str = "ou_integ_imager",
        chat_id: str = "oc_integ_image",
        message_id: str = "",
    ) -> str:
        """Push a p2 im.message.receive_v1 image event over the WS."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = message_id or f"om_integ_img_{n}"
        event = {
            "schema": "2.0",
            "header": {
                "event_id": f"evt-{mid}",
                "event_type": "im.message.receive_v1",
                "create_time": str(int(time.time() * 1000)),
                "token": "integ-mock-verification",
                "app_id": "cli_integ_mock",
                "tenant_key": "integ_tenant",
            },
            "event": {
                "sender": {
                    "sender_id": {
                        "open_id": sender_open_id,
                        "user_id": "u_integ",
                        "union_id": "on_integ",
                    },
                    "sender_type": "user",
                    "tenant_key": "integ_tenant",
                },
                "message": {
                    "message_id": mid,
                    "create_time": str(int(time.time() * 1000)),
                    "chat_id": chat_id,
                    "chat_type": "p2p",
                    "message_type": "image",
                    "content": json.dumps({"image_key": image_key}),
                },
            },
        }
        frame_bytes = _build_event_frame(event)
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no lark SDK client connected"
        conn.send(frame_bytes)
        return mid

    def sent_texts(self) -> list[str]:
        """Texts of recorded outbound im/v1/messages sends."""
        out: list[str] = []
        with self._lock:
            calls = list(self.api_calls)
        for call in calls:
            if "/im/v1/messages" not in call["path"]:
                continue
            body = call.get("body") or {}
            content = body.get("content")
            if not content:
                continue
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                parsed = {}
            text = parsed.get("text") or parsed.get("content")
            if text:
                out.append(str(text))
            elif content:
                out.append(str(content))
        return out

    def wait_for_sent_text(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.sent_texts():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
