# -*- coding: utf-8 -*-
"""Minimal mock Matrix homeserver for integration tests.

The Matrix channel drives matrix-nio's AsyncClient against the
``homeserver`` URL — plain HTTP (client-server API). This mock serves
just enough endpoints for token login + sync + send:

* ``GET  /_matrix/client/v3/account/whoami`` -> bot identity
* ``GET  /_matrix/client/v3/sync``           -> long-poll event queue
* ``PUT  /_matrix/client/v3/rooms/{id}/send/{type}/{txn}`` -> recorded
* misc (versions/joined_rooms/join/keys/...) -> benign 200s
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handler touches own instance

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

BOT_USER_ID = "@integ-mock-bot:mock.local"
BOT_DEVICE_ID = "INTEGMOCKDEV"

_SEND_RE = re.compile(
    r"^/_matrix/client/v3/rooms/([^/]+)/send/([^/]+)/(.+)$",
)


class MockMatrixHomeserver:
    """Mock Matrix homeserver on localhost (HTTP only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.http_port: int = 0
        # Pending timeline events per room, drained by /sync.
        self._pending: list[tuple[str, dict[str, Any]]] = []
        self._batch = 0
        self._event_counter = 0
        # Recorded room sends.
        self.sent_events: list[dict[str, Any]] = []
        self._http_server: Optional[ThreadingHTTPServer] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_http()

    @property
    def homeserver(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    # -------------------------------------------------------------- #
    # HTTP
    # -------------------------------------------------------------- #

    # pylint: disable-next=too-many-statements
    def _start_http(self) -> None:  # noqa: C901
        mock = self

        # pylint: disable-next=too-many-statements
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

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/_matrix/client/versions":
                    self._json({"versions": ["v1.1", "v1.5"]})
                    return
                if path == "/_matrix/client/v3/account/whoami":
                    self._json(
                        {
                            "user_id": BOT_USER_ID,
                            "device_id": BOT_DEVICE_ID,
                        },
                    )
                    return
                if path == "/_matrix/client/v3/sync":
                    self._json(mock._build_sync())
                    return
                if path == "/_matrix/client/v3/joined_rooms":
                    self._json({"joined_rooms": []})
                    return
                if path.endswith("/joined_members"):
                    # Rooms with "group" in the id report 3 members
                    # (group room, mention gate applies); others report
                    # 2 (bot + sender => DM, mention gate skipped).
                    joined = {
                        BOT_USER_ID: {"display_name": "Integ Bot"},
                        "@integ-user:mock.local": {
                            "display_name": "Integ User",
                        },
                    }
                    if "group" in path:
                        joined["@integ-user2:mock.local"] = {
                            "display_name": "Integ User 2",
                        }
                    self._json({"joined": joined})
                    return
                self._json({})

            def do_PUT(self) -> None:
                path = urlparse(self.path).path
                body = self._read_body()
                match = _SEND_RE.match(path)
                if match:
                    room_id, msgtype = match.group(1), match.group(2)
                    with mock._lock:
                        mock.sent_events.append(
                            {
                                "room_id": room_id,
                                "type": msgtype,
                                "content": body,
                            },
                        )
                        mock._event_counter += 1
                        n = mock._event_counter
                    self._json({"event_id": f"$mockevent{n}"})
                    return
                self._json({})

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                _ = self._read_body()
                if "/keys/" in path or path.endswith("/keys/upload"):
                    self._json(
                        {"one_time_key_counts": {"signed_curve25519": 50}},
                    )
                    return
                if "/join" in path:
                    self._json({"room_id": "!integmockroom:mock.local"})
                    return
                self._json({})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = server.server_address[1]
        self._http_server = server
        threading.Thread(
            target=server.serve_forever,
            name="mock-matrix-http",
            daemon=True,
        ).start()

    # -------------------------------------------------------------- #
    # sync payloads
    # -------------------------------------------------------------- #

    def _build_sync(self) -> dict:
        """Drain pending events into a sync response (long-poll-ish)."""
        deadline = time.time() + 2.0
        drained: list[tuple[str, dict[str, Any]]] = []
        while time.time() < deadline:
            with self._lock:
                if self._pending:
                    drained = list(self._pending)
                    self._pending.clear()
                    break
            time.sleep(0.1)
        with self._lock:
            self._batch += 1
            batch = f"batch-{self._batch}"
        rooms_join: dict[str, Any] = {}
        for room_id, event in drained:
            room = rooms_join.setdefault(
                room_id,
                {
                    "timeline": {
                        "events": [],
                        "limited": False,
                        "prev_batch": batch,
                    },
                    "state": {"events": []},
                    "ephemeral": {"events": []},
                    "account_data": {"events": []},
                    "summary": {},
                    "unread_notifications": {},
                },
            )
            room["timeline"]["events"].append(event)
        return {
            "next_batch": batch,
            "rooms": {"join": rooms_join, "invite": {}, "leave": {}},
            "presence": {"events": []},
            "account_data": {"events": []},
            "to_device": {"events": []},
            "device_lists": {"changed": [], "left": []},
            "device_one_time_keys_count": {},
        }

    # -------------------------------------------------------------- #
    # test-facing helpers
    # -------------------------------------------------------------- #

    def push_text_event(
        self,
        *,
        text: str,
        room_id: str = "!integmockroom:mock.local",
        sender: str = "@integ-user:mock.local",
        mention_bot: bool = False,
    ) -> str:
        """Queue an m.room.message text event for the next /sync.

        ``mention_bot`` attaches an ``m.mentions`` block targeting the
        bot, which group rooms require before the channel responds.
        """
        with self._lock:
            self._event_counter += 1
            n = self._event_counter
        event_id = f"$integincoming{n}"
        content: dict[str, Any] = {"msgtype": "m.text", "body": text}
        if mention_bot:
            content["m.mentions"] = {"user_ids": [BOT_USER_ID]}
        event = {
            "type": "m.room.message",
            "event_id": event_id,
            "sender": sender,
            "origin_server_ts": int(time.time() * 1000),
            "content": content,
            "room_id": room_id,
            "unsigned": {},
        }
        with self._lock:
            self._pending.append((room_id, event))
        return event_id

    def push_typed_event(
        self,
        *,
        msgtype: str,
        text: str,
        room_id: str = "!integmockroom:mock.local",
        sender: str = "@integ-user:mock.local",
    ) -> str:
        """Queue an m.room.message with a custom msgtype."""
        with self._lock:
            self._event_counter += 1
            n = self._event_counter
        event_id = f"$integtyped{n}"
        event = {
            "type": "m.room.message",
            "event_id": event_id,
            "sender": sender,
            "origin_server_ts": int(time.time() * 1000),
            "content": {"msgtype": msgtype, "body": text},
            "room_id": room_id,
            "unsigned": {},
        }
        with self._lock:
            self._pending.append((room_id, event))
        return event_id

    def sent_texts(self) -> list[str]:
        with self._lock:
            events = list(self.sent_events)
        return [
            str((e.get("content") or {}).get("body", ""))
            for e in events
            if (e.get("content") or {}).get("body")
        ]

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
