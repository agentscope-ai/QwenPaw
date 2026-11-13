# -*- coding: utf-8 -*-
"""Shared message reduction for live replay state and legacy imports."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any


def _decode(frame: str) -> dict[str, Any] | None:
    """Decode one SSE frame, returning None for non-object payloads."""
    lines = []
    for line in frame.splitlines():
        if line.startswith("data: "):
            lines.append(line[6:])
    if not lines:
        return None
    value = json.loads("\n".join(lines))
    return value if isinstance(value, dict) else None


def _encode(value: dict[str, Any]) -> str:
    """Encode one compact SSE event."""
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n"


def _upsert_message(
    response: dict[str, Any],
    messages: dict[str, dict[str, Any]],
    incoming: dict[str, Any],
) -> None:
    """Apply the SDK response builder's message replacement semantics."""
    message_id = incoming.get("id")
    if not isinstance(message_id, str):
        return
    existing = messages.get(message_id)
    if existing is None:
        existing = dict(incoming)
        existing["content"] = list(incoming.get("content") or [])
        messages[message_id] = existing
        response.setdefault("output", []).append(existing)
        return
    content = existing.get("content")
    existing.update(incoming)
    if not incoming.get("content"):
        existing["content"] = content


def _merge_delta(
    message: dict[str, Any],
    previous: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> bool:
    """Merge a delta into the previous incremental block when possible."""
    if not previous or not previous.get("delta"):
        return False
    if incoming.get("type") == "text" and previous.get("type") == "text":
        old_text = previous.get("text", "")
        new_text = incoming.get("text", "")
        previous["text"] = f"{old_text}{new_text}"
        return True
    if incoming.get("type") != "data":
        return False
    if message.get("type") not in {
        "plugin_call",
        "tool_call",
        "mcp_call",
    }:
        previous["data"] = incoming.get("data")
        return True
    old_data = dict(previous.get("data") or {})
    for key, value in (incoming.get("data") or {}).items():
        old_value = old_data.get(key)
        if isinstance(old_value, str) and isinstance(value, str):
            old_data[key] = f"{old_value}{value}"
        else:
            old_data[key] = value
    previous["data"] = old_data
    return True


def _apply_content(
    message: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    """Apply one content event using the runtime builder's rules."""
    content = message.setdefault("content", [])
    if incoming.get("delta"):
        previous = content[-1] if content else None
        if _merge_delta(message, previous, incoming):
            return
        content.append(dict(incoming))
        return
    if content:
        content[-1].update(incoming)
    else:
        content.append(dict(incoming))


def _apply_response(
    response: dict[str, Any],
    messages: dict[str, dict[str, Any]],
    incoming: dict[str, Any],
) -> None:
    """Merge a response event without dropping accumulated output."""
    output = response.setdefault("output", [])
    for key, value in incoming.items():
        if key != "output":
            response[key] = value
    response["output"] = output
    for message in incoming.get("output") or []:
        if isinstance(message, dict):
            _upsert_message(response, messages, message)


def _apply_runtime_event(
    response: dict[str, Any],
    messages: dict[str, dict[str, Any]],
    message_owner: dict[str, dict[str, Any]],
    event: dict[str, Any],
) -> None:
    """Apply one message or content event to a known response."""
    if event.get("object") == "message":
        if event.get("type") == "heartbeat":
            return
        _upsert_message(response, messages, event)
        message_id = event.get("id")
        if isinstance(message_id, str):
            message_owner[message_id] = messages[message_id]
        return
    message_id = event.get("msg_id")
    if not isinstance(message_id, str):
        raise ValueError("content has no string message id")
    message = message_owner.get(message_id)
    if message is None:
        raise ValueError("content precedes its message")
    _apply_content(message, event)


def _apply_pending_runtime(
    response: dict[str, Any],
    messages: dict[str, dict[str, Any]],
    message_owner: dict[str, dict[str, Any]],
    pending: list[dict[str, Any]],
) -> None:
    """Apply runtime events retained before their replaced response slot."""
    for event in pending:
        _apply_runtime_event(
            response,
            messages,
            message_owner,
            event,
        )


class ReplayMessageState:
    """Reduce events once, keeping complete messages instead of deltas."""

    def __init__(self) -> None:
        self.response: dict[str, Any] = {}
        self.messages: dict[str, dict[str, Any]] = {}

    def apply(self, event: dict[str, Any]) -> None:
        kind = event.get("object")
        if kind == "response":
            _apply_response(self.response, self.messages, event)
        elif kind == "message":
            if event.get("type") != "heartbeat":
                _upsert_message(self.response, self.messages, event)
        elif kind == "content":
            message_id = event.get("msg_id")
            message = (
                self.messages.get(message_id)
                if isinstance(message_id, str)
                else None
            )
            if message is not None:
                _apply_content(message, event)

    def remove(self, message_id: str) -> None:
        self.messages.pop(message_id, None)
        self.response["output"] = list(self.messages.values())


# The branches mirror the three runtime envelope object variants and the
# control-event fallback in one bounded protocol dispatcher.
# pylint: disable-next=too-many-branches
def materialize_replay(events: list[str]) -> list[str]:
    """Return canonical response snapshots plus non-runtime control events.

    Any malformed or unsupported replay falls back to the original events.
    This makes materialization a performance optimization, never a source of
    history loss.
    """
    responses: OrderedDict[str, dict[str, Any]] = OrderedDict()
    response_messages: dict[str, dict[str, dict[str, Any]]] = {}
    message_owner: dict[str, dict[str, Any]] = {}
    pending_runtime: list[dict[str, Any]] = []
    usage_controls: list[str] = []
    controls: list[str] = []
    current_id: str | None = None
    try:
        for frame in events:
            event = _decode(frame)
            if event is None:
                raise ValueError("invalid SSE replay event")
            kind = event.get("object")
            if kind == "response":
                response_id = event.get("id")
                if not isinstance(response_id, str):
                    raise ValueError("response has no string id")
                response = responses.setdefault(
                    response_id,
                    {**event, "output": []},
                )
                messages = response_messages.setdefault(response_id, {})
                if pending_runtime:
                    _apply_pending_runtime(
                        response,
                        messages,
                        message_owner,
                        pending_runtime,
                    )
                    pending_runtime = []
                _apply_response(response, messages, event)
                for key, message in messages.items():
                    message_owner[key] = message
                current_id = response_id
            elif kind in {"message", "content"}:
                if current_id is None:
                    pending_runtime.append(event)
                    continue
                response = responses[current_id]
                messages = response_messages[current_id]
                _apply_runtime_event(
                    response,
                    messages,
                    message_owner,
                    event,
                )
            elif event.get("type") == "turn_usage":
                usage_controls.append(frame)
            else:
                controls.append(frame)
    except (KeyError, TypeError, ValueError):
        return events
    if not responses:
        return events
    if pending_runtime:
        return events
    snapshots = [_encode(response) for response in responses.values()]
    return usage_controls + snapshots + controls
