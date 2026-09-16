# -*- coding: utf-8 -*-
"""Minimal mock XiaoYi (Huawei A2A) gateway for integration tests.

The XiaoYi channel connects a WebSocket (aiohttp) to ``ws_url`` with
HMAC auth headers (not validated here) and speaks JSON-RPC-ish A2A
frames. The mock accepts the connection, swallows the init message
and heartbeats, lets tests push ``message/stream`` requests, and
records every frame the channel sends back (streaming task updates).
"""
from __future__ import annotations

# pylint: disable=protected-access  # nested handler touches own instance

import json
import threading
import time
from typing import Any, Optional

from websockets.sync.server import serve as ws_serve


class MockXiaoYi:
    """Mock XiaoYi A2A WS gateway on localhost."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self.ws_port: int = 0
        self._ws_conn: Optional[Any] = None
        self._connected = threading.Event()
        self._counter = 0
        # All JSON frames sent by the channel (init/heartbeat/responses).
        self.frames: list[dict[str, Any]] = []
        self._ws_server: Optional[Any] = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._start_ws()

    @property
    def ws_url(self) -> str:
        """Value for the XiaoYi channel ``ws_url`` config field."""
        return f"ws://127.0.0.1:{self.ws_port}/openclaw/v1/ws/link"

    def _start_ws(self) -> None:
        mock = self

        def handler(conn: Any) -> None:
            with mock._lock:
                mock._ws_conn = conn
            mock._connected.set()
            try:
                for raw in conn:
                    try:
                        frame = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    with mock._lock:
                        mock.frames.append(frame)
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
            name="mock-xiaoyi-ws",
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

    def push_message_stream(
        self,
        *,
        text: str,
        agent_id: str,
        session_id: str = "integ-xy-session",
        task_id: str = "",
    ) -> str:
        """Push an A2A message/stream request to the channel."""
        with self._lock:
            self._counter += 1
            n = self._counter
        tid = task_id or f"integ-xy-task-{n}"
        frame = {
            "jsonrpc": "2.0",
            "id": f"req-{tid}",
            "method": "message/stream",
            "agentId": agent_id,
            "params": {
                "id": tid,
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": text}],
                    "messageId": f"msg-{tid}",
                },
            },
        }
        with self._lock:
            conn = self._ws_conn
        assert conn is not None, "no xiaoyi client connected"
        conn.send(json.dumps(frame))
        return tid

    def reply_texts(self) -> list[str]:
        """Extract text content from recorded channel frames."""
        out: list[str] = []
        with self._lock:
            frames = list(self.frames)
        for frame in frames:
            raw = json.dumps(frame, ensure_ascii=False)
            out.append(raw)
        return out

    def wait_for_reply(
        self,
        predicate,
        *,
        timeout: float = 90.0,
    ) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.reply_texts():
                if predicate(text):
                    return text
            time.sleep(0.2)
        return None
