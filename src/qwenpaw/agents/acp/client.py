# -*- coding: utf-8 -*-
"""ACP client adapter built on the official Python SDK."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from acp import RequestError, session_notification
from acp.contrib.session_state import SessionAccumulator, ToolCallView
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    CurrentModeUpdate,
    RequestPermissionResponse,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)

from .core import ACPAgentConfig, SuspendedPermission
from .permissions import ACPPermissionAdapter

MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]


class ACPHostedClient:
    """ACP client callback implementation for delegated agents."""

    def __init__(
        self,
        *,
        agent_name: str,
        agent_config: ACPAgentConfig,
        cwd: str,
    ) -> None:
        self.agent_name = agent_name
        self.tool_parse_mode = agent_config.tool_parse_mode
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)
        self._session_acc = SessionAccumulator()
        self._on_message: MessageHandler | None = None
        self._assistant_text = ""
        self._emitted_assistant_text = ""
        self._thinking_active = False
        self._pending_permission: SuspendedPermission | None = None
        self._permission_future: asyncio.Future[RequestPermissionResponse] | None = None
        self._permission_requested = asyncio.Event()

    @property
    def pending_permission(self) -> SuspendedPermission | None:
        return self._pending_permission

    def update_cwd(self, cwd: str) -> None:
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)

    def start_prompt(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._assistant_text = ""
        self._emitted_assistant_text = ""
        self._thinking_active = False
        self._pending_permission = None
        self._permission_requested.clear()
        self._session_acc = SessionAccumulator()

    def resume_prompt(self, on_message: MessageHandler) -> None:
        self._on_message = on_message
        self._permission_requested.clear()

    async def wait_for_permission_request(self) -> None:
        await self._permission_requested.wait()

    def resolve_permission(self, option_id: str) -> None:
        if self._pending_permission is None or self._permission_future is None:
            raise ValueError("No pending ACP permission request.")

        selected_option = self._permission_adapter.resolve_option_by_id(
            self._pending_permission.options,
            option_id,
        )
        if selected_option is None:
            raise ValueError(
                "respond requires the exact selected permission option id "
                "from the provided options.",
            )

        if not self._permission_future.done():
            self._permission_future.set_result(
                self._permission_adapter.selected_response(selected_option),
            )

    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> RequestPermissionResponse:
        _ = session_id
        await self.flush_assistant_text()

        suspended = self._permission_adapter.build_suspended_permission(
            agent=self.agent_name,
            tool_call=tool_call,
            options=options,
        )
        await self._emit_message(
            {
                "type": "permission_request",
                "title": suspended.summary or suspended.tool_name,
                "options": suspended.options,
                "tool_kind": suspended.tool_kind,
                "tool_name": suspended.tool_name,
            },
            True,
        )

        if self._permission_adapter.is_hard_blocked(tool_call):
            return self._permission_adapter.cancelled_response()

        self._pending_permission = suspended
        self._permission_requested.set()
        self._permission_future = asyncio.get_running_loop().create_future()
        try:
            return await self._permission_future
        finally:
            self._pending_permission = None
            self._permission_future = None
            self._permission_requested.clear()

    async def session_update(
        self,
        session_id: str,
        update: UserMessageChunk
        | AgentMessageChunk
        | AgentThoughtChunk
        | ToolCallStart
        | ToolCallProgress
        | AgentPlanUpdate
        | AvailableCommandsUpdate
        | CurrentModeUpdate,
        **_: Any,
    ) -> None:
        if isinstance(update, AgentMessageChunk):
            self._thinking_active = False
            await self._accumulate_assistant_content(update.content)
            return

        await self.flush_assistant_text()

        if isinstance(update, AgentThoughtChunk):
            self._thinking_active = True
            return

        self._thinking_active = False

        if isinstance(update, (ToolCallStart, ToolCallProgress)):
            snapshot = self._session_acc.apply(
                session_notification(session_id, update),
            )
            event = self._tool_event_from_state(
                update,
                snapshot.tool_calls.get(update.tool_call_id),
            )
            if event is not None:
                await self._emit_message(event, True)
            return

        if isinstance(
            update,
            (
                CurrentModeUpdate,
                AgentPlanUpdate,
                AvailableCommandsUpdate,
                UserMessageChunk,
            ),
        ):
            self._session_acc.apply(session_notification(session_id, update))

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        _ = params
        self._unsupported_method(method)

    async def ext_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        _ = params
        self._unsupported_method(method)

    async def emit_permission_resolved(self) -> None:
        await self._emit_message(
            {
                "type": "status",
                "status": "permission_resolved",
                "summary": "Permission resolved, resuming execution.",
            },
            True,
        )

    async def finish_prompt(self) -> dict[str, Any] | None:
        await self.flush_assistant_text()
        if self._assistant_text:
            return {
                "type": "text",
                "text": self._assistant_text,
                "is_chunk": False,
            }
        return None

    async def flush_assistant_text(self) -> None:
        await self._emit_assistant_text_delta()

    async def _emit_message(self, payload: dict[str, Any], is_last: bool) -> None:
        if self._on_message is None:
            return
        await self._on_message(payload, is_last)

    async def _accumulate_assistant_content(self, content: Any) -> None:
        text = self._extract_text_from_content(content)
        if not text:
            return
        self._merge_assistant_text(text)

    async def _emit_assistant_text_delta(self) -> None:
        if not self._assistant_text:
            return
        if self._assistant_text == self._emitted_assistant_text:
            return
        delta = self._assistant_text[len(self._emitted_assistant_text) :]
        if not delta:
            return
        self._emitted_assistant_text = self._assistant_text
        await self._emit_message(
            {"type": "text", "text": delta, "is_chunk": False},
            False,
        )

    def _merge_assistant_text(self, text: str) -> None:
        if not text:
            return
        if text == self._assistant_text:
            return
        if not self._assistant_text:
            self._assistant_text = text
            return
        if text.startswith(self._assistant_text):
            self._assistant_text = text
            return

        max_overlap = min(len(self._assistant_text), len(text))
        for size in range(max_overlap, 0, -1):
            if self._assistant_text.endswith(text[:size]):
                self._assistant_text = self._assistant_text + text[size:]
                return
        self._assistant_text = self._assistant_text + text

    def _extract_text_from_content(self, content: Any) -> str:
        if hasattr(content, "text") and isinstance(getattr(content, "text", None), str):
            return str(content.text)
        if hasattr(content, "name") and hasattr(content, "uri"):
            return str(getattr(content, "name", None) or getattr(content, "uri", None) or "")
        if hasattr(content, "resource"):
            resource = getattr(content, "resource", None)
            if resource is not None:
                text = getattr(resource, "text", None)
                if isinstance(text, str) and text:
                    return text
                blob = getattr(resource, "blob", None)
                if isinstance(blob, str) and blob:
                    return blob
            return ""
        if isinstance(content, list):
            parts = [self._extract_text_from_content(item) for item in content]
            return "".join(part for part in parts if part)
        if isinstance(content, dict):
            if content.get("type") == "text" and isinstance(content.get("text"), str):
                return str(content["text"])
            return ""
        return ""

    def _tool_event_from_state(
        self,
        update: ToolCallStart | ToolCallProgress,
        state: ToolCallView | None,
    ) -> dict[str, Any] | None:
        call_id = str(getattr(update, "tool_call_id", "") or "")
        if not call_id:
            return None

        title = self._string_value(
            getattr(state, "title", None),
        ) or self._string_value(getattr(update, "title", None)) or "unknown"
        kind = self._string_value(
            getattr(state, "kind", None),
        ) or self._string_value(getattr(update, "kind", None)) or "other"
        status = str(
            getattr(state, "status", None)
            or getattr(update, "status", None)
            or "pending"
        )
        target = self._tool_target(state, update)
        detail = self._tool_detail(kind, title, state, update) or title
        summary = self._stringify_summary(
            getattr(state, "raw_output", None),
        ) or self._stringify_summary(getattr(update, "raw_output", None))

        event: dict[str, Any] = {
            "type": self._tool_event_type(update, state),
            "name": title,
            "call_id": call_id,
            "title": title,
            "kind": kind,
            "status": status,
        }
        if detail:
            event["detail"] = detail
        if target:
            event["target"] = target
        if summary:
            event["summary"] = summary
        return event

    def _tool_event_type(
        self,
        update: ToolCallStart | ToolCallProgress,
        state: ToolCallView | None,
    ) -> str:
        if isinstance(update, ToolCallStart) or self.tool_parse_mode == "update_detail":
            return "tool_start"
        status = str(getattr(state, "status", None) or getattr(update, "status", None) or "pending")
        if status in {"completed", "failed"}:
            return "tool_end"
        return "tool_update"

    def _tool_detail(
        self,
        kind: str,
        title: str,
        state: ToolCallView | None,
        update: ToolCallStart | ToolCallProgress,
    ) -> str | None:
        target = self._tool_target(state, update)
        if self.tool_parse_mode == "call_title":
            return title
        if kind == "execute":
            return self._tool_input_text(state, update, "command") or title
        if kind == "read":
            return (
                self._tool_input_text(state, update, "file_path", "filePath", "path")
                or target
                or title
            )
        if kind == "search":
            return self._tool_input_text(state, update, "path", "pattern") or target or title
        if kind == "edit":
            return title or target
        return title

    def _tool_target(
        self,
        state: ToolCallView | None,
        update: ToolCallStart | ToolCallProgress,
    ) -> str | None:
        locations = getattr(state, "locations", None) or getattr(update, "locations", None) or []
        for location in locations:
            path = getattr(location, "path", None)
            if path:
                return str(path)
            if isinstance(location, dict) and location.get("path"):
                return str(location["path"])
        return None

    def _tool_input_text(
        self,
        state: ToolCallView | None,
        update: ToolCallStart | ToolCallProgress,
        *keys: str,
    ) -> str | None:
        raw_inputs = (
            getattr(state, "raw_input", None),
            getattr(update, "raw_input", None),
        )
        for raw_input in raw_inputs:
            if not isinstance(raw_input, dict):
                continue
            for key in keys:
                value = raw_input.get(key)
                if isinstance(value, list):
                    for item in reversed(value):
                        text = self._string_value(item)
                        if text:
                            return text
                else:
                    text = self._string_value(value)
                    if text:
                        return text
        return None

    def _string_value(self, value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _stringify_summary(self, value: Any) -> str | None:
        if value is None:
            return None
        return self._string_value(value) if isinstance(value, str) else str(value)
