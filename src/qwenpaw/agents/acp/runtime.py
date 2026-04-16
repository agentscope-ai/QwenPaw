# -*- coding: utf-8 -*-
"""Minimal ACP runtime built on stdio JSON-RPC transport."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from .core import (
    ACPAgentConfig,
    ACPErrors,
    ACPProtocolError,
    ACPTransportError,
    PermissionResolution,
    SuspendedPermission,
)
from .tool_parser import ACPToolCallParser
from .transport import (
    ACPTransport,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

PermissionHandler = Callable[[dict[str, Any]], Awaitable[PermissionResolution]]
MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]
logger = logging.getLogger(__name__)


class ACPRuntime:
    PROTOCOL_VERSION = 1
    PROMPT_TIMEOUT_SECONDS = 1800.0
    THINKING_STATUS_INTERVAL_SECONDS = 5.0
    EMIT_THINKING_STATUS = False

    def __init__(self, agent_name: str, agent_config: ACPAgentConfig):
        self.agent_name = agent_name
        self.transport = ACPTransport(agent_name, agent_config)
        self._suspended_permission: SuspendedPermission | None = None
        self._prompt_task: asyncio.Task | None = None
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._tool_calls: dict[str, dict[str, Any]] = {}
        self._assistant_text = ""
        self._emitted_assistant_text = ""
        self._thinking_active = False
        self._tool_parser = ACPToolCallParser(
            agent_name,
            agent_config.tool_parse_mode,
            self._tool_calls,
        )

    async def start(self, cwd: str) -> None:
        await self.transport.start(cwd=cwd)
        response = await self.transport.send_request(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "clientCapabilities": {"requestPermission": True},
                "clientInfo": {"name": "QwenPaw", "version": "1.0.0"},
            },
            timeout=30.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"initialize failed for {self.agent_name}: {response.error}",
                agent=self.agent_name,
            )

    @property
    def suspended_permission(self) -> SuspendedPermission | None:
        return self._suspended_permission

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True

            prompt_task = self._prompt_task
            self._prompt_task = None
            self._suspended_permission = None
            self._tool_calls.clear()
            self._reset_prompt_state()

            if prompt_task is not None and not prompt_task.done():
                prompt_task.cancel()
                try:
                    await prompt_task
                except (asyncio.CancelledError, Exception):
                    pass

            await self.transport.close()

    async def new_session(self, cwd: str) -> str:
        response = await self.transport.send_request(
            "session/new",
            {"cwd": cwd, "mcpServers": []},
            timeout=60.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"session/new failed for {self.agent_name}: {response.error}",
                agent=self.agent_name,
            )
        session_id = (response.result or {}).get("sessionId")
        if not session_id:
            raise ACPProtocolError(
                "session/new response did not include sessionId",
                agent=self.agent_name,
            )
        return str(session_id)

    async def load_session(self, session_id: str, cwd: str) -> str:
        response = await self.transport.send_request(
            "session/load",
            {"sessionId": session_id, "cwd": cwd, "mcpServers": []},
            timeout=60.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"session/load failed for {self.agent_name}: {response.error}",
                agent=self.agent_name,
            )
        return str((response.result or {}).get("sessionId") or session_id)

    async def prompt(
        self,
        *,
        session_id: str,
        prompt_blocks: list[dict[str, Any]],
        permission_handler: PermissionHandler,
        on_message: MessageHandler,
        timeout: float = PROMPT_TIMEOUT_SECONDS,
    ) -> dict[str, Any] | None:
        if self._closed:
            raise ACPTransportError(
                f"ACP runtime for {self.agent_name} is already closed",
                agent=self.agent_name,
            )
        self._suspended_permission = None
        self._tool_calls.clear()
        self._reset_prompt_state()
        self._prompt_task = asyncio.create_task(
            self.transport.send_request(
                "session/prompt",
                {"sessionId": session_id, "prompt": prompt_blocks},
                timeout=timeout,
            ),
        )
        return await self._drain_and_finalize_prompt(
            permission_handler=permission_handler,
            on_message=on_message,
        )

    async def resume_prompt_after_permission(
        self,
        *,
        permission_result: dict[str, Any],
        on_message: MessageHandler,
        permission_handler: PermissionHandler,
    ) -> dict[str, Any] | None:
        if self._suspended_permission is None:
            raise ACPErrors(
                "No suspended permission to resume",
                agent=self.agent_name,
            )
        request_id = self._suspended_permission.request_id
        self._suspended_permission = None
        await self.transport.send_result(request_id, permission_result)
        await on_message(
            {
                "type": "status",
                "status": "permission_resolved",
                "summary": "Permission resolved, resuming execution.",
            },
            True,
        )
        return await self._drain_and_finalize_prompt(
            permission_handler=permission_handler,
            on_message=on_message,
        )

    async def _drain_and_finalize_prompt(
        self,
        *,
        permission_handler: PermissionHandler,
        on_message: MessageHandler,
    ) -> dict[str, Any] | None:
        suspended = await self._drain_events_until_done(
            permission_handler=permission_handler,
            on_message=on_message,
        )
        if suspended:
            return None
        try:
            return await self._finalize_prompt(on_message)
        finally:
            self._prompt_task = None

    async def _drain_events_until_done(
        self,
        *,
        permission_handler: PermissionHandler,
        on_message: MessageHandler,
    ) -> bool:
        assert self._prompt_task is not None
        prompt_task = self._prompt_task
        last_status_at = 0.0
        while True:
            try:
                incoming = await asyncio.wait_for(
                    self.transport.incoming.get(),
                    timeout=0.1 if not prompt_task.done() else 0.5,
                )
            except asyncio.TimeoutError:
                if prompt_task.done():
                    break
                now = asyncio.get_running_loop().time()
                if (
                    self.EMIT_THINKING_STATUS
                    and now - last_status_at
                    >= self.THINKING_STATUS_INTERVAL_SECONDS
                ):
                    last_status_at = now
                    await on_message(
                        {
                            "type": "status",
                            "status": "agent_thinking",
                            "summary": f"{self.agent_name} is working...",
                        },
                        True,
                    )
                continue

            if isinstance(incoming, JSONRPCRequest):
                suspended = await self._handle_request(
                    request=incoming,
                    permission_handler=permission_handler,
                    on_message=on_message,
                )
                if suspended:
                    return True
                continue

            await self._handle_notification(incoming, on_message)
        return False

    async def _finalize_prompt(
        self,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        assert self._prompt_task is not None
        try:
            response = await self._prompt_task
        except ACPTransportError as exc:
            response = JSONRPCResponse(id=None, error={"message": str(exc)})

        if response.is_error:
            await on_message(
                {"type": "error", "message": str(response.error)},
                True,
            )

        result_payload = response.result or {}
        await self._accumulate_and_emit_assistant_text(
            self._extract_final_assistant_text(result_payload),
            on_message,
        )
        await on_message(
            {
                "type": "status",
                "status": "run_finished",
                "result": result_payload,
            },
            True,
        )
        return result_payload

    async def _handle_request(
        self,
        *,
        request: JSONRPCRequest,
        permission_handler: PermissionHandler,
        on_message: MessageHandler,
    ) -> bool:
        if request.method == "session/request_permission":
            params = request.params or {}
            await on_message({"type": "permission_request", **params}, True)
            resolution = await permission_handler(params)
            if resolution.suspended is not None:
                resolution.suspended.request_id = request.id
                self._suspended_permission = resolution.suspended
                return True
            await self.transport.send_result(
                request.id,
                resolution.result or {},
            )
            return False

        await self.transport.send_error(
            request.id,
            code=-32601,
            message=f"Unsupported ACP client request: {request.method}",
        )
        return False

    async def _handle_notification(
        self,
        notification: JSONRPCNotification | JSONRPCResponse,
        on_message: MessageHandler,
    ) -> None:
        if not isinstance(notification, JSONRPCNotification):
            return
        if notification.method != "session/update":
            return

        params = notification.params or {}
        update = params.get("update")
        if not isinstance(update, dict):
            return

        update_type = str(update.get("sessionUpdate") or "").lower()
        handled = False
        if update_type == "agent_message_chunk":
            self._thinking_active = False
            await self._accumulate_assistant_content(
                update.get("content"),
                on_message=None,
            )
            handled = True
        else:
            await self._emit_assistant_text_delta(on_message)
            handled = await self._handle_non_message_update(
                update_type=update_type,
                update=update,
                on_message=on_message,
            )

        if not handled:
            logger.warning(
                "Ignored unsupported ACP update from %s: %s",
                self.agent_name,
                json.dumps(update, ensure_ascii=False, sort_keys=True),
            )

    async def _handle_non_message_update(
        self,
        *,
        update_type: str,
        update: dict[str, Any],
        on_message: MessageHandler,
    ) -> bool:
        if update_type == "agent_thought_chunk":
            return await self._handle_thought_update(on_message)
        self._thinking_active = False
        if update_type == "tool_call":
            event = self._tool_parser.handle_tool_call_created(update)
            return await self._emit_optional_event(event, on_message)
        if update_type == "tool_call_update":
            event = self._tool_parser.handle_tool_call_updated(update)
            return await self._emit_optional_event(event, on_message)
        if update_type == "error":
            await on_message(
                {
                    "type": "error",
                    "message": str(update.get("message") or "Unknown error"),
                    "raw": update,
                },
                True,
            )
            return True
        return False

    async def _handle_thought_update(self, on_message: MessageHandler) -> bool:
        if self._thinking_active:
            return True
        self._thinking_active = True
        if self.EMIT_THINKING_STATUS:
            await on_message(
                {
                    "type": "status",
                    "status": "agent_thinking",
                    "summary": f"{self.agent_name} is working...",
                },
                True,
            )
        return True

    async def _emit_optional_event(
        self,
        event: dict[str, Any] | None,
        on_message: MessageHandler,
    ) -> bool:
        if event is None:
            return False
        await on_message(event, True)
        return True

    def _reset_prompt_state(self) -> None:
        self._assistant_text = ""
        self._emitted_assistant_text = ""
        self._thinking_active = False

    async def _accumulate_assistant_content(
        self,
        content: Any,
        on_message: MessageHandler | None,
    ) -> None:
        text = self._extract_text_from_content(content)
        if not text:
            return
        await self._accumulate_and_emit_assistant_text(text, on_message)

    async def _accumulate_and_emit_assistant_text(
        self,
        text: str,
        on_message: MessageHandler | None,
    ) -> None:
        self._merge_assistant_text(text)
        if on_message is not None:
            await self._emit_assistant_text_delta(on_message)

    def _merge_assistant_text(self, text: str) -> None:
        if not text:
            return
        if text == self._assistant_text:
            return
        self._assistant_text = self._merge_text(self._assistant_text, text)

    async def _emit_assistant_text_delta(
        self,
        on_message: MessageHandler,
    ) -> None:
        if not self._assistant_text:
            return
        if self._assistant_text == self._emitted_assistant_text:
            return
        delta = self._assistant_text[len(self._emitted_assistant_text) :]
        if not delta:
            return
        self._emitted_assistant_text = self._assistant_text
        await on_message(
            {"type": "text", "text": delta, "is_chunk": False},
            False,
        )

    def _extract_final_assistant_text(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        return self._first_non_empty_text(
            payload.get("content"),
            payload.get("message"),
        )

    def _first_non_empty_text(self, *contents: Any) -> str:
        for content in contents:
            text = self._extract_text_from_content(content).strip()
            if text:
                return text
        return ""

    def _merge_text(self, existing: str, incoming: str) -> str:
        if not existing:
            return incoming
        if not incoming:
            return existing
        if incoming.startswith(existing):
            return incoming

        max_overlap = min(len(existing), len(incoming))
        for size in range(max_overlap, 0, -1):
            if existing.endswith(incoming[:size]):
                return existing + incoming[size:]
        return existing + incoming

    def _extract_text_from_content(self, content: Any) -> str:
        if isinstance(content, dict):
            if content.get("type") == "text":
                text = content.get("text")
                if isinstance(text, str):
                    return text
            return ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = self._extract_text_from_content(item)
                if text:
                    parts.append(text)
            return "".join(parts)
        return ""
