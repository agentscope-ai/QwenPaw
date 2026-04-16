# -*- coding: utf-8 -*-
"""ACP tool call parsing helpers."""
from __future__ import annotations

from typing import Any


class ACPToolCallParser:
    """Parse ACP tool call events into normalized tool messages."""

    _STATE_KEYS = (
        "title",
        "kind",
        "status",
        "rawInput",
        "rawOutput",
        "content",
    )

    def __init__(
        self,
        agent_name: str,
        tool_parse_mode: str,
        tool_calls: dict[str, dict[str, Any]],
    ):
        self.agent_name = agent_name
        self.tool_parse_mode = tool_parse_mode
        self.tool_calls = tool_calls

    def handle_tool_call_created(
        self,
        update: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._handle_tool_call(update, created=True)

    def handle_tool_call_updated(
        self,
        update: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._handle_tool_call(update)

    def _handle_tool_call(
        self,
        update: dict[str, Any],
        *,
        created: bool = False,
    ) -> dict[str, Any] | None:
        call_id = self._string_value(update.get("toolCallId"))
        if not call_id:
            return None
        state = self.tool_calls.setdefault(call_id, {"toolCallId": call_id})
        self._merge_update_into_state(state, update)
        if created and self.tool_parse_mode == "update_detail":
            return None
        return self._tool_message_from_state(
            state,
            event_type=self._event_type(state, created=created),
        )

    def _event_type(self, state: dict[str, Any], *, created: bool) -> str:
        if created or self.tool_parse_mode == "update_detail":
            return "tool_start"
        return {
            "completed": "tool_end",
            "failed": "tool_end",
            "in_progress": "tool_update",
        }.get(
            self._string_value(state.get("status")) or "pending",
            "tool_start",
        )

    def _merge_update_into_state(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
    ) -> None:
        for key in self._STATE_KEYS:
            value = update.get(key)
            if value is not None:
                state[key] = value
        if isinstance(update.get("locations"), list):
            state["locations"] = update["locations"]
        state.setdefault("kind", "other")
        state.setdefault("status", "pending")
        state.setdefault("locations", [])

    def _tool_message_from_state(
        self,
        state: dict[str, Any],
        *,
        event_type: str,
    ) -> dict[str, Any]:
        title = self._string_value(state.get("title")) or ""
        message: dict[str, Any] = {
            "type": event_type,
            "name": title or "unknown",
            "call_id": str(state.get("toolCallId") or ""),
            "title": title,
            "kind": self._string_value(state.get("kind")) or "other",
            "raw": {
                "toolCallId": state.get("toolCallId"),
                "status": state.get("status"),
            },
        }
        message["detail"] = (
            self._extract_detail(state, kind=message["kind"]) or title
        )
        target = self._extract_target(state)
        if target:
            message["target"] = target
        summary = self._stringify_summary(state.get("rawOutput"))
        if summary:
            message["summary"] = summary
            message["result"] = state.get("rawOutput")
        return message

    def _extract_detail(
        self,
        state: dict[str, Any],
        *,
        kind: str,
    ) -> str | None:
        if self.tool_parse_mode == "call_title":
            return self._string_value(state.get("title"))
        if kind == "execute":
            return self._extract_command(state)
        if kind == "read":
            return self._raw_input_first(
                state,
                "file_path",
                "filePath",
                "path",
            )
        if kind == "search":
            return self._raw_input_first(
                state,
                "path",
                "pattern",
                fallback=self._extract_target(state)
                if self.tool_parse_mode == "call_detail"
                else None,
            )
        return None

    def _extract_target(self, state: dict[str, Any]) -> str | None:
        for location in state.get("locations") or []:
            if isinstance(location, dict):
                path = self._string_value(location.get("path"))
                if path:
                    return path
        return None

    def _extract_command(self, state: dict[str, Any]) -> str | None:
        command = self._raw_input_value(state, "command")
        if isinstance(command, list):
            for item in reversed(command):
                text = self._string_value(item)
                if text:
                    return text
            return None
        return self._string_value(command)

    def _raw_input_first(
        self,
        state: dict[str, Any],
        *keys: str,
        fallback: str | None = None,
    ) -> str | None:
        for key in keys:
            text = self._string_value(self._raw_input_value(state, key))
            if text:
                return text
        return fallback

    def _raw_input_value(self, state: dict[str, Any], key: str) -> Any:
        raw_input = state.get("rawInput")
        if not isinstance(raw_input, dict):
            return None
        return raw_input.get(key)

    def _string_value(self, value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        return None

    def _stringify_summary(self, value: Any) -> str | None:
        if value is None:
            return None
        return (
            self._string_value(value) if isinstance(value, str) else str(value)
        )
