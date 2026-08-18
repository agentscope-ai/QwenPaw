# -*- coding: utf-8 -*-
"""Minimal mock Telegram Bot API for integration tests.

The Telegram channel talks plain HTTP (Bot API long polling), so a
single HTTP server is enough — no WebSocket. Point the channel's
``base_url`` config field at this server and it will call
``{base_url}/bot{token}/<method>``.

Implemented methods:
  * ``getMe``       -> bot identity (needed at startup)
  * ``getUpdates``  -> long-poll queue fed by ``push_text_message``
  * ``sendMessage`` -> recorded outbound reply
  * ``sendChatAction`` / ``deleteMessage`` / ``editMessageText`` -> 200
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handler touches own instance

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

BOT_ID = 900000001
BOT_USERNAME = "integ_mock_bot"


class MockTelegramAPI:
    """Mock Telegram Bot API server on localhost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        # Pending updates handed out by getUpdates.
        self._pending: list[dict[str, Any]] = []
        self._update_id = 10000
        self._message_id = 500
        # Recorded sendMessage calls.
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
        """Value for the Telegram channel ``base_url`` config field."""
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

            def _method_name(self) -> str:
                path = urlparse(self.path).path
                return path.rsplit("/", 1)[-1] if "/" in path else path

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if not raw:
                    return {}
                ctype = self.headers.get("Content-Type", "")
                try:
                    if "json" in ctype:
                        return json.loads(raw)
                    parsed = parse_qs(raw.decode())
                    return {k: v[0] for k, v in parsed.items()}
                except Exception:  # noqa: BLE001
                    return {}

            def _dispatch(self, body: dict) -> None:
                name = self._method_name()
                if name == "getMe":
                    self._json(
                        {
                            "ok": True,
                            "result": {
                                "id": BOT_ID,
                                "is_bot": True,
                                "first_name": "Integ Mock Bot",
                                "username": BOT_USERNAME,
                                "can_join_groups": True,
                                "can_read_all_group_messages": False,
                                "supports_inline_queries": False,
                            },
                        },
                    )
                    return
                if name == "getUpdates":
                    self._json({"ok": True, "result": mock._take_updates()})
                    return
                if name == "sendMessage":
                    with mock._lock:
                        mock.sent_messages.append(dict(body))
                        mock._message_id += 1
                        mid = mock._message_id
                    self._json(
                        {
                            "ok": True,
                            "result": {
                                "message_id": mid,
                                "date": int(time.time()),
                                "chat": {
                                    "id": body.get("chat_id"),
                                    "type": "private",
                                },
                                "text": body.get("text", ""),
                            },
                        },
                    )
                    return
                # Everything else: benign OK.
                self._json({"ok": True, "result": True})

            def do_POST(self) -> None:
                self._dispatch(self._read_body())

            def do_GET(self) -> None:
                query = parse_qs(urlparse(self.path).query)
                body = {k: v[0] for k, v in query.items()}
                self._dispatch(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-telegram-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # update queue
    # -------------------------------------------------------------- #

    def _take_updates(self) -> list[dict[str, Any]]:
        """Return and clear pending updates (long-poll friendly)."""
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
        chat_id: int = 777001,
        user_id: int = 777001,
        username: str = "integ_tester",
        chat_type: str = "private",
        mention_bot: bool = False,
    ) -> int:
        """Queue an incoming text message update; return its update_id.

        ``mention_bot`` prefixes ``@<bot>`` and attaches the matching
        ``mention`` entity, which group messages need for the channel
        to treat them as addressed to the bot.
        """
        entities: list[dict[str, Any]] = []
        if mention_bot:
            handle = f"@{BOT_USERNAME}"
            text = f"{handle} {text}"
            entities.append(
                {"type": "mention", "offset": 0, "length": len(handle)},
            )
        with self._lock:
            self._update_id += 1
            uid = self._update_id
            self._message_id += 1
            mid = self._message_id
            message: dict[str, Any] = {
                "message_id": mid,
                "date": int(time.time()),
                "text": text,
                "chat": {
                    "id": chat_id,
                    "type": chat_type,
                    "first_name": username,
                },
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": username,
                    "username": username,
                },
            }
            if entities:
                message["entities"] = entities
            update = {"update_id": uid, "message": message}
            self._pending.append(update)
        return uid

    def push_photo_message(
        self,
        *,
        chat_id: int = 777001,
        user_id: int = 777001,
        caption: str = "",
    ) -> int:
        """Queue an inbound photo message update."""
        with self._lock:
            self._update_id += 1
            uid = self._update_id
            self._message_id += 1
            mid = self._message_id
            message = {
                "message_id": mid,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "integ_tester",
                },
                "photo": [
                    {
                        "file_id": "integ-file-id-small",
                        "file_unique_id": "u1",
                        "width": 90,
                        "height": 90,
                        "file_size": 1234,
                    },
                ],
            }
            if caption:
                message["caption"] = caption
            self._pending.append({"update_id": uid, "message": message})
        return uid

    def push_command_message(
        self,
        *,
        command: str = "/version",
        chat_id: int = 777001,
        user_id: int = 777001,
    ) -> int:
        """Queue a bot_command message with the proper entity."""
        with self._lock:
            self._update_id += 1
            uid = self._update_id
            self._message_id += 1
            mid = self._message_id
            self._pending.append(
                {
                    "update_id": uid,
                    "message": {
                        "message_id": mid,
                        "date": int(time.time()),
                        "text": command,
                        "entities": [
                            {
                                "type": "bot_command",
                                "offset": 0,
                                "length": len(command),
                            },
                        ],
                        "chat": {"id": chat_id, "type": "private"},
                        "from": {
                            "id": user_id,
                            "is_bot": False,
                            "first_name": "integ_tester",
                        },
                    },
                },
            )
        return uid

    # -------------------------------------------------------------- #
    # assertions
    # -------------------------------------------------------------- #

    def sent_texts(self) -> list[str]:
        with self._lock:
            msgs = list(self.sent_messages)
        return [str(m.get("text", "")) for m in msgs if m.get("text")]

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
