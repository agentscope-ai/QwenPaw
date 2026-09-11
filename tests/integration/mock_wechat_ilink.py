# -*- coding: utf-8 -*-
"""Minimal mock WeChat iLink backend for integration tests.

The WeChat channel is HTTP-only long polling against ``base_url``:

* ``POST /ilink/bot/getupdates``   -> long-poll queue of msgs
* ``POST /ilink/bot/sendmessage``  -> recorded outbound reply
* other ilink endpoints            -> benign {"ret": 0}

With ``bot_token`` set in config, start() skips QR login entirely.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handler touches own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse


class MockWeChatILink:
    """Mock iLink backend on localhost (HTTP only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self._pending: list[dict[str, Any]] = []
        self._cursor = 0
        self._msg_counter = 0
        self.sent_messages: list[dict[str, Any]] = []
        self._http_server: Optional[ThreadingHTTPServer] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_http()

    @property
    def base_url(self) -> str:
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

            def _json(self, obj: dict) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(200)
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
                path = urlparse(self.path).path
                body = self._read_body()
                if path.endswith("/getupdates"):
                    msgs = mock._take_msgs()
                    with mock._lock:
                        mock._cursor += 1
                        cursor = f"buf-{mock._cursor}"
                    self._json(
                        {
                            "ret": 0,
                            "msgs": msgs,
                            "get_updates_buf": cursor,
                            "longpolling_timeout_ms": 2000,
                        },
                    )
                    return
                if path.endswith("/sendmessage"):
                    with mock._lock:
                        mock.sent_messages.append(body.get("msg") or {})
                    self._json({"ret": 0})
                    return
                self._json({"ret": 0})

            def do_GET(self) -> None:
                self._json({"ret": 0})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-wechat-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # queue
    # -------------------------------------------------------------- #

    def _take_msgs(self) -> list[dict[str, Any]]:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with self._lock:
                if self._pending:
                    out = list(self._pending)
                    self._pending.clear()
                    return out
            time.sleep(0.1)
        return []

    def push_text_message(
        self,
        *,
        text: str,
        from_user_id: str = "integuser@im.wechat",
        context_token: str = "",
    ) -> str:
        """Queue an inbound WeChat text message; return context_token."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        token = context_token or f"ctx-integ-{n}"
        msg = {
            "from_user_id": from_user_id,
            "to_user_id": "integbot@im.wechat",
            "context_token": token,
            "message_type": 1,
            "msg_id": f"integ-wx-msg-{n}",
            "create_time": int(time.time()),
            "item_list": [
                {"type": 1, "text_item": {"text": text}},
            ],
        }
        with self._lock:
            self._pending.append(msg)
        return token

    def push_group_text_message(
        self,
        *,
        text: str,
        group_id: str,
        from_user_id: str = "integuser@im.wechat",
        context_token: str = "",
    ) -> str:
        """Queue an inbound group text message; return context_token."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        token = context_token or f"ctx-integ-g-{n}"
        msg = {
            "from_user_id": from_user_id,
            "to_user_id": "integbot@im.wechat",
            "context_token": token,
            "message_type": 1,
            "group_id": group_id,
            "msg_id": f"integ-wx-gmsg-{n}",
            "create_time": int(time.time()),
            "item_list": [
                {"type": 1, "text_item": {"text": text}},
            ],
        }
        with self._lock:
            self._pending.append(msg)
        return token

    def push_image_message(
        self,
        *,
        url: str = "https://example.invalid/wx-image.jpg",
        aes_key: str = "integ-aes-key",
        from_user_id: str = "integuser@im.wechat",
        context_token: str = "",
    ) -> str:
        """Queue an inbound WeChat image message."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        token = context_token or f"ctx-integ-img-{n}"
        msg = {
            "from_user_id": from_user_id,
            "to_user_id": "integbot@im.wechat",
            "context_token": token,
            "message_type": 1,
            "msg_id": f"integ-wx-img-{n}",
            "create_time": int(time.time()),
            "item_list": [
                {
                    "type": 2,
                    "image_item": {"url": url, "aeskey": aes_key},
                },
            ],
        }
        with self._lock:
            self._pending.append(msg)
        return token

    # -------------------------------------------------------------- #
    # assertions
    # -------------------------------------------------------------- #

    def sent_texts(self) -> list[str]:
        with self._lock:
            msgs = list(self.sent_messages)
        out: list[str] = []
        for msg in msgs:
            for item in msg.get("item_list") or []:
                text = (item.get("text_item") or {}).get("text")
                if text:
                    out.append(str(text))
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
