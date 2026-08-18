# -*- coding: utf-8 -*-
"""Minimal mock DingTalk backend for integration tests.

Mocks the three surfaces the DingTalk channel touches when the
``endpoint`` config field points at this server:

* ``POST /v1.0/gateway/connections/open`` -> ws:// endpoint + ticket
  (dingtalk_stream SDK's open-connection API).
* WS gateway: accepts the SDK connection and lets tests push
  CALLBACK frames (topic ``/v1.0/im/bot/messages/get``).
* ``POST /session/webhook`` -> outbound reply sink. Incoming messages
  carry ``sessionWebhook`` pointing here, so replies go through
  ``_send_via_session_webhook`` (aiohttp) and get recorded without
  the alibaba OpenAPI SDK.
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handlers touch own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve

CHATBOT_TOPIC = "/v1.0/im/bot/messages/get"


class MockDingTalkIM:
    """Mock DingTalk backend (open-connection + WS + webhook sink)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        self.ws_port: int = 0
        # Recorded webhook replies: dicts with path/body.
        self.webhook_posts: list[dict[str, Any]] = []
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
    def endpoint(self) -> str:
        """Value for the DingTalk channel ``endpoint`` config field."""
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def session_webhook(self) -> str:
        return f"http://127.0.0.1:{self.http_port}/session/webhook"

    # -------------------------------------------------------------- #
    # HTTP: open-connection API + session webhook sink
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
                if self.path == "/v1.0/gateway/connections/open":
                    self._json(
                        200,
                        {
                            "endpoint": f"ws://127.0.0.1:{mock.ws_port}",
                            "ticket": "integ-mock-ticket",
                        },
                    )
                    return
                with mock._lock:
                    mock.webhook_posts.append(
                        {"path": self.path, "body": body},
                    )
                self._json(200, {"errcode": 0, "errmsg": "ok"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-dingtalk-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # WS gateway
    # -------------------------------------------------------------- #

    def _start_ws(self) -> None:
        mock = self

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn  # pylint: disable=protected-access
            mock._connected.set()  # pylint: disable=protected-access
            try:
                for _raw in conn:
                    # SDK sends ACK frames back; nothing to do.
                    pass
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
            name="mock-dingtalk-ws",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def wait_connected(self, timeout: float = 60.0) -> bool:
        """Block until the dingtalk_stream SDK connected to the WS."""
        return self._connected.wait(timeout)

    def reset_connected(self) -> None:
        self._connected.clear()

    @property
    def has_connection(self) -> bool:
        """True if a WS client connection is currently alive."""
        with self._lock:
            return self._ws_conn is not None

    def push_chatbot_text(
        self,
        *,
        text: str,
        sender_staff_id: str = "integ-dt-user",
        conversation_id: str = "cid-integ-dt",
        conversation_type: str = "1",
        msg_id: str = "",
    ) -> str:
        """Push one chatbot text CALLBACK to the connected SDK client.

        Returns the msgId used, for correlation in assertions.
        """
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = msg_id or f"integ-dt-msg-{n}"
        data = {
            "msgtype": "text",
            "text": {"content": text},
            "msgId": mid,
            "createAt": str(int(time.time() * 1000)),
            "conversationType": conversation_type,
            "conversationId": conversation_id,
            "senderId": f"uid-{sender_staff_id}",
            "senderStaffId": sender_staff_id,
            "senderNick": "Integ Tester",
            "chatbotUserId": "bot-integ-dt",
            "sessionWebhook": self.session_webhook,
            "sessionWebhookExpiredTime": int(
                (time.time() + 3600) * 1000,
            ),
        }
        if conversation_type == "2":
            data["conversationTitle"] = "integ group"
            data["isAdmin"] = False
            # handler.py gates group replies on isInAtList (bot @-ed).
            data["isInAtList"] = True
            data["atUsers"] = [{"dingtalkId": "bot-integ-dt"}]
        frame = {
            "specVersion": "1.0",
            "type": "CALLBACK",
            "headers": {
                "topic": CHATBOT_TOPIC,
                "messageId": mid,
                "contentType": "application/json",
                "time": str(int(time.time() * 1000)),
            },
            "data": json.dumps(data),
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no dingtalk SDK client connected"
        conn.send(json.dumps(frame))
        return mid

    def push_chatbot_rich_text(
        self,
        *,
        segments: list[dict],
        sender_staff_id: str = "integ-dt-rich",
        conversation_id: str = "cid-integ-dt-rich",
        msg_id: str = "",
    ) -> str:
        """Push a richText CALLBACK (msgtype=richText).

        ``segments`` is the DingTalk richText list, e.g.
        ``[{"text": "hello"}, {"text": "world"}]``.
        """
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = msg_id or f"integ-dt-rich-{n}"
        data = {
            "msgtype": "richText",
            "content": {"richText": segments},
            "msgId": mid,
            "createAt": str(int(time.time() * 1000)),
            "conversationType": "1",
            "conversationId": conversation_id,
            "senderId": f"uid-{sender_staff_id}",
            "senderStaffId": sender_staff_id,
            "senderNick": "Integ Rich Tester",
            "chatbotUserId": "bot-integ-dt",
            "sessionWebhook": self.session_webhook,
            "sessionWebhookExpiredTime": int((time.time() + 3600) * 1000),
        }
        frame = {
            "specVersion": "1.0",
            "type": "CALLBACK",
            "headers": {
                "topic": CHATBOT_TOPIC,
                "messageId": mid,
                "contentType": "application/json",
                "time": str(int(time.time() * 1000)),
            },
            "data": json.dumps(data),
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no dingtalk SDK client connected"
        conn.send(json.dumps(frame))
        return mid

    def push_chatbot_picture(
        self,
        *,
        download_code: str = "integ-dt-dlcode-1",
        caption: str = "",
        sender_staff_id: str = "integ-dt-pic",
        conversation_id: str = "cid-integ-dt-pic",
        msg_id: str = "",
    ) -> str:
        """Push a richText CALLBACK containing a picture item."""
        with self._lock:
            self._msg_counter += 1
            n = self._msg_counter
        mid = msg_id or f"integ-dt-pic-{n}"
        items: list[dict] = [{"downloadCode": download_code}]
        if caption:
            items.insert(0, {"text": caption})
        data = {
            "msgtype": "richText",
            "content": {"richText": items},
            "msgId": mid,
            "createAt": str(int(time.time() * 1000)),
            "conversationType": "1",
            "conversationId": conversation_id,
            "senderId": f"uid-{sender_staff_id}",
            "senderStaffId": sender_staff_id,
            "senderNick": "Integ Pic Tester",
            "chatbotUserId": "bot-integ-dt",
            "sessionWebhook": self.session_webhook,
            "sessionWebhookExpiredTime": int((time.time() + 3600) * 1000),
        }
        frame = {
            "specVersion": "1.0",
            "type": "CALLBACK",
            "headers": {
                "topic": CHATBOT_TOPIC,
                "messageId": mid,
                "contentType": "application/json",
                "time": str(int(time.time() * 1000)),
            },
            "data": json.dumps(data),
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no dingtalk SDK client connected"
        conn.send(json.dumps(frame))
        return mid

    def replied_texts(self) -> list[str]:
        """Text contents of recorded session-webhook replies."""
        out: list[str] = []
        with self._lock:
            posts = list(self.webhook_posts)
        for post in posts:
            body = post.get("body") or {}
            text = (body.get("text") or {}).get("content")
            if text:
                out.append(str(text))
            md = (body.get("markdown") or {}).get("text")
            if md:
                out.append(str(md))
        return out

    def wait_for_reply(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        """Poll webhook replies until predicate(text) matches."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.replied_texts():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
