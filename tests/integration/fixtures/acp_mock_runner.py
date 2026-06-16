# -*- coding: utf-8 -*-
"""Stdio Mock ACP Runner for integration tests.

Speaks ACP JSON-RPC v2.0 over stdin/stdout (NDJSON: one JSON message
per line).  Behaviour is driven by environment variables so that
individual tests can script different scenarios without forking this
file.

Supported request methods:
- ``initialize`` → returns protocol_version=1 and minimal capabilities
- ``session/new`` → returns a fixed session_id
- ``session/prompt`` → emits a stream of ``session/update`` notifications
  back to the host (via stdout) and finally responds with
  ``stop_reason="end_turn"``.  When ``ACP_MOCK_REQUEST_PERMISSION=1`` the
  runner first sends a ``session/request_permission`` request and waits
  for the host's reply before completing the prompt.
- ``session/close`` (unstable) → returns null
- ``session/list`` → returns empty list

Environment variables (set by the test):
- ``ACP_MOCK_REPLY_TEXT`` — text emitted as ``agent_message_chunk``
  during prompt (default: "mock reply")
- ``ACP_MOCK_REQUEST_PERMISSION`` — when "1", request permission first
- ``ACP_MOCK_PERMISSION_OPTIONS`` — JSON list of option ids (default
  ``["allow", "deny"]``)
- ``ACP_MOCK_FAIL_INITIALIZE`` — when "1", reject initialize with error
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    """Write one JSON message + newline to stdout, then flush."""
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def _read_message() -> dict[str, Any] | None:
    """Read one NDJSON line from stdin via asyncio."""
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def _request(
    request_id: int,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


_SESSION_ID = "mock-session-1"
_PERMISSION_REQUEST_ID = 9001


class _Runner:
    def __init__(self) -> None:
        self.reply_text = os.environ.get(
            "ACP_MOCK_REPLY_TEXT",
            "mock reply",
        )
        self.request_permission = (
            os.environ.get("ACP_MOCK_REQUEST_PERMISSION") == "1"
        )
        self.fail_initialize = (
            os.environ.get("ACP_MOCK_FAIL_INITIALIZE") == "1"
        )
        try:
            self.permission_options = json.loads(
                os.environ.get(
                    "ACP_MOCK_PERMISSION_OPTIONS",
                    '["allow", "deny"]',
                ),
            )
        except json.JSONDecodeError:
            self.permission_options = ["allow", "deny"]
        # Used to correlate permission response with our pending request.
        self._permission_future: asyncio.Future | None = None

    async def handle(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        msg_id = msg.get("id")

        # Response from host to a request we made (permission).
        if method is None and msg_id is not None:
            if self._permission_future and not self._permission_future.done():
                self._permission_future.set_result(msg)
            return

        if method == "initialize":
            if self.fail_initialize:
                _emit(_err(msg_id, -32603, "mock failure"))
                return
            _emit(
                _ok(
                    msg_id,
                    {
                        "protocolVersion": 1,
                        "agentCapabilities": {
                            "promptCapabilities": {
                                "image": False,
                                "audio": False,
                                "embeddedContext": False,
                            },
                            "loadSession": False,
                        },
                        "authMethods": [],
                    },
                ),
            )
        elif method == "session/new":
            _emit(_ok(msg_id, {"sessionId": _SESSION_ID}))
        elif method == "session/prompt":
            await self._handle_prompt(msg_id)
        elif method == "session/close":
            _emit(_ok(msg_id, None))
        elif method == "session/list":
            _emit(_ok(msg_id, {"sessions": []}))
        elif method == "session/cancel":
            # Notification, no response.
            pass
        else:
            _emit(_err(msg_id, -32601, f"method not found: {method}"))

    async def _handle_prompt(self, msg_id: Any) -> None:
        if self.request_permission:
            self._permission_future = asyncio.get_event_loop().create_future()
            _emit(
                _request(
                    _PERMISSION_REQUEST_ID,
                    "session/request_permission",
                    {
                        "sessionId": _SESSION_ID,
                        "toolCall": {
                            "toolCallId": "mock-tool-1",
                            "title": "Mock tool wants permission",
                            "kind": "execute",
                            "status": "pending",
                            "content": [],
                            "locations": [],
                            "rawInput": {},
                        },
                        "options": [
                            {
                                "optionId": opt_id,
                                "name": opt_id.title(),
                                "kind": (
                                    "allow_once"
                                    if opt_id == "allow"
                                    else "reject_once"
                                ),
                            }
                            for opt_id in self.permission_options
                        ],
                    },
                ),
            )
            response = await self._permission_future
            chosen = (
                response.get("result", {})
                .get("outcome", {})
                .get("optionId", "deny")
            )
            if chosen == "deny" or chosen.startswith("reject"):
                _emit(_ok(msg_id, {"stopReason": "refusal"}))
                return

        # Stream a single agent_message_chunk update.
        _emit(
            _notification(
                "session/update",
                {
                    "sessionId": _SESSION_ID,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {
                            "type": "text",
                            "text": self.reply_text,
                        },
                    },
                },
            ),
        )
        _emit(_ok(msg_id, {"stopReason": "end_turn"}))


async def _main() -> int:
    runner = _Runner()
    while True:
        msg = await _read_message()
        if msg is None:
            return 0
        try:
            await runner.handle(msg)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"mock runner error: {exc}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
