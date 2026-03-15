# -*- coding: utf-8 -*-
"""ACP runtime built on a bidirectional stdio transport."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import ACPHarnessConfig
from .errors import ACPProtocolError, ACPTransportError
from .transport import ACPTransport, JSONRPCNotification, JSONRPCRequest
from .types import AcpEvent

logger = logging.getLogger(__name__)

PermissionHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
EventHandler = Callable[[AcpEvent], Awaitable[None]]


class ACPRuntime:
    """Manage one ACP harness process and one active chat session."""

    PROTOCOL_VERSION = 1
    PROMPT_TIMEOUT_SECONDS = 1800.0
    PROMPT_DRAIN_GRACE_SECONDS = 1.0

    def __init__(self, harness_name: str, harness_config: ACPHarnessConfig):
        self.harness_name = harness_name
        self.harness_config = harness_config
        self.transport = ACPTransport(harness_name, harness_config)
        self.capabilities: dict[str, Any] = {}

    async def start(self, cwd: str) -> None:
        """Start the harness and perform initialize handshake."""
        await self.transport.start(cwd=Path(cwd))
        response = await self.transport.send_request(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                    "requestPermission": True,
                },
                "clientInfo": {
                    "name": "CoPaw",
                    "version": "1.0.0",
                },
            },
            timeout=30.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"initialize failed for {self.harness_name}: {response.error}",
            )

        result = response.result or {}
        agent_capabilities = result.get("agentCapabilities") or result.get("capabilities") or {}
        if isinstance(agent_capabilities, dict):
            self.capabilities = agent_capabilities

    async def close(self) -> None:
        """Shutdown the harness transport."""
        await self.transport.close()

    async def new_session(self, cwd: str) -> str:
        """Create a new ACP session."""
        response = await self.transport.send_request(
            "session/new",
            {
                "cwd": cwd,
                "mcpServers": [],
            },
            timeout=60.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"session/new failed for {self.harness_name}: {response.error}",
            )
        session_id = (response.result or {}).get("sessionId")
        if not session_id:
            raise ACPProtocolError("session/new response did not include sessionId")
        return str(session_id)

    async def load_session(self, session_id: str, cwd: str) -> str:
        """Load an existing ACP session."""
        response = await self.transport.send_request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": cwd,
            },
            timeout=60.0,
        )
        if response.is_error:
            raise ACPTransportError(
                f"session/load failed for {self.harness_name}: {response.error}",
            )
        loaded_id = (response.result or {}).get("sessionId") or session_id
        return str(loaded_id)

    async def prompt(
        self,
        *,
        chat_id: str,
        session_id: str,
        prompt_blocks: list[dict[str, Any]],
        permission_handler: PermissionHandler,
        on_event: EventHandler,
        timeout: float = PROMPT_TIMEOUT_SECONDS,
    ) -> None:
        """Send a prompt and stream updates until the turn completes."""
        logger.info(
            "ACP prompt starting for %s: chat_id=%s session_id=%s",
            self.harness_name,
            chat_id,
            session_id,
        )
        
        prompt_task = asyncio.create_task(
            self.transport.send_request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": prompt_blocks,
                },
                timeout=timeout,
            ),
        )

        run_finished_received = False
        
        while True:
            try:
                incoming = await asyncio.wait_for(
                    self.transport.incoming.get(),
                    timeout=(
                        self.PROMPT_DRAIN_GRACE_SECONDS
                        if prompt_task.done()
                        else 0.1
                    ),
                )
            except asyncio.TimeoutError:
                if prompt_task.done():
                    logger.debug(
                        "ACP prompt task done for %s, draining remaining notifications",
                        self.harness_name,
                    )
                    # Drain any remaining notifications with a short timeout
                    drain_count = 0
                    while True:
                        try:
                            incoming = await asyncio.wait_for(
                                self.transport.incoming.get(),
                                timeout=0.5,
                            )
                            drain_count += 1
                            if isinstance(incoming, JSONRPCNotification):
                                # Check if this is a run_finished notification
                                update = incoming.params.get("update") or incoming.params
                                if isinstance(update, dict):
                                    update_type = (
                                        update.get("sessionUpdate")
                                        or update.get("type")
                                        or update.get("updateType")
                                        or ""
                                    )
                                    if str(update_type).lower() == "run_finished":
                                        run_finished_received = True
                                        logger.info(
                                            "ACP run_finished received during drain for %s",
                                            self.harness_name,
                                        )
                                await self._handle_notification(
                                    chat_id=chat_id,
                                    session_id=session_id,
                                    notification=incoming,
                                    on_event=on_event,
                                )
                        except asyncio.TimeoutError:
                            break
                    logger.debug(
                        "ACP drained %d notifications for %s",
                        drain_count,
                        self.harness_name,
                    )
                    break
                continue

            if isinstance(incoming, JSONRPCRequest):
                await self._handle_request(
                    chat_id=chat_id,
                    session_id=session_id,
                    request=incoming,
                    permission_handler=permission_handler,
                    on_event=on_event,
                )
                continue

            # Check if this is a run_finished notification
            if isinstance(incoming, JSONRPCNotification):
                update = incoming.params.get("update") or incoming.params
                if isinstance(update, dict):
                    update_type = (
                        update.get("sessionUpdate")
                        or update.get("type")
                        or update.get("updateType")
                        or ""
                    )
                    if str(update_type).lower() == "run_finished":
                        run_finished_received = True
                        logger.info(
                            "ACP run_finished received for %s",
                            self.harness_name,
                        )

            await self._handle_notification(
                chat_id=chat_id,
                session_id=session_id,
                notification=incoming,
                on_event=on_event,
            )

        response = await prompt_task
        logger.info(
            "ACP prompt completed for %s: error=%s run_finished_received=%s",
            self.harness_name,
            response.is_error,
            run_finished_received,
        )
        
        if response.is_error:
            await on_event(
                AcpEvent(
                    type="error",
                    chat_id=chat_id,
                    session_id=session_id,
                    payload={"message": str(response.error)},
                ),
            )

        # Always emit run_finished to ensure frontend knows the turn is complete
        await on_event(
            AcpEvent(
                type="run_finished",
                chat_id=chat_id,
                session_id=session_id,
                payload={"result": response.result or {}},
            ),
        )
        logger.info("ACP run_finished event emitted for %s", self.harness_name)

    async def _handle_request(
        self,
        *,
        chat_id: str,
        session_id: str,
        request: JSONRPCRequest,
        permission_handler: PermissionHandler,
        on_event: EventHandler,
    ) -> None:
        method = request.method.replace("-", "_")
        if "permission" not in method.lower():
            logger.warning(
                "Unsupported ACP client request from %s: method=%s params=%s",
                self.harness_name,
                request.method,
                request.params,
            )
            await self.transport.send_error(
                request.id,
                code=-32601,
                message=f"Unsupported ACP client request: {request.method}",
            )
            return

        params = request.params or {}
        summary_payload = dict(params)
        summary_payload.setdefault("harness", self.harness_name)
        await on_event(
            AcpEvent(
                type="permission_request",
                chat_id=chat_id,
                session_id=session_id,
                payload=summary_payload,
            ),
        )

        result = await permission_handler(params)
        await self.transport.send_result(request.id, result)

        await on_event(
            AcpEvent(
                type="permission_resolved",
                chat_id=chat_id,
                session_id=session_id,
                payload={
                    "summary": "外部 Agent 权限请求已处理 / External agent permission request resolved.",
                },
            ),
        )

    async def _handle_notification(
        self,
        *,
        chat_id: str,
        session_id: str,
        notification: JSONRPCNotification,
        on_event: EventHandler,
    ) -> None:
        logger.debug(
            "ACP notification from %s: method=%s params=%s",
            self.harness_name,
            notification.method,
            notification.params,
        )
        
        if notification.method not in {"session/update", "sessionUpdate"}:
            return

        update = notification.params.get("update") or notification.params
        if not isinstance(update, dict):
            return

        update_type = (
            update.get("sessionUpdate")
            or update.get("type")
            or update.get("updateType")
            or ""
        )
        normalized = str(update_type).lower()
        payload = self._normalize_payload(update)

        logger.debug(
            "ACP update from %s: type=%s normalized=%s",
            self.harness_name,
            update_type,
            normalized,
        )

        event_type = {
            "agent_message_chunk": "assistant_chunk",
            "agent_thought_chunk": "thought_chunk",
            "tool_call": "tool_start",
            "tool_call_update": "tool_update",
            "tool_call_end": "tool_end",
            "plan": "plan_update",
            "usage_update": "usage_update",
            "available_commands_update": "commands_update",
            "run_finished": "run_finished",
            "error": "error",
        }.get(normalized)

        if event_type is None:
            logger.debug("Unknown ACP update type from %s: %s", self.harness_name, normalized)
            return

        logger.debug(
            "ACP event from %s: type=%s chat_id=%s",
            self.harness_name,
            event_type,
            chat_id,
        )

        await on_event(
            AcpEvent(
                type=event_type,  # type: ignore[arg-type]
                chat_id=chat_id,
                session_id=session_id,
                payload=payload,
            ),
        )

    def _normalize_payload(self, update: dict[str, Any]) -> dict[str, Any]:
        session_update = str(
            update.get("sessionUpdate")
            or update.get("type")
            or update.get("updateType")
            or "",
        ).lower()

        if session_update == "agent_message_chunk":
            content = update.get("content")
            if isinstance(content, dict):
                return {"text": content.get("text") or ""}
            if isinstance(content, list):
                texts = [
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict) and block.get("text")
                ]
                return {"text": "".join(texts)}
            return {"text": str(content or "")}

        if session_update in {"tool_call", "tool_call_update", "tool_call_end"}:
            tool = (
                update.get("toolCall")
                or update.get("tool_call")
            )
            if not isinstance(tool, dict):
                tool = update
            tool_input = (
                tool.get("input")
                or tool.get("arguments")
                or tool.get("rawInput")
                or {}
            )
            if not isinstance(tool_input, dict):
                tool_input = {"raw": tool_input}
            tool_output = self._extract_tool_output(tool)
            return {
                "id": tool.get("id") or tool.get("toolCallId"),
                "name": tool.get("name") or tool.get("tool") or tool.get("title"),
                "input": tool_input,
                "output": tool_output,
                "status": tool.get("status"),
                "summary": tool.get("summary"),
                "detail": tool.get("detail"),
            }

        if session_update == "plan":
            plan = update.get("plan") or update.get("content") or update
            return {"plan": plan}

        if session_update == "available_commands_update":
            return {
                "commands": update.get("availableCommands") or update.get("commands") or [],
            }

        if session_update == "usage_update":
            return update.get("usage") if isinstance(update.get("usage"), dict) else update

        if session_update == "error":
            return {"message": update.get("message") or update.get("error") or "ACP error"}

        return update

    def _extract_tool_output(self, tool: dict[str, Any]) -> Any:
        if tool.get("output") is not None:
            return tool.get("output")

        content = tool.get("content")
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                block = item.get("content")
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if text:
                        chunks.append(str(text))
            if chunks:
                return "\n".join(chunks)

        raw_output = tool.get("rawOutput")
        if isinstance(raw_output, dict):
            if raw_output.get("output") is not None:
                return raw_output.get("output")
            if raw_output.get("error") is not None:
                return raw_output.get("error")

        return None
