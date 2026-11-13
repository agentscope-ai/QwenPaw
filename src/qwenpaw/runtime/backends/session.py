# -*- coding: utf-8 -*-
"""Persist provider-neutral third-party turns in QwenPaw sessions."""

from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import Any

from agentscope.message import Msg
from agentscope.state import AgentState

from ..._session_signals import (
    TRANSCRIPT_RECORDING_READY_KEY,
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
    TURN_COMMIT_KEY,
)
from .._state_utils import StateProxy
from ...schemas import AgentResponse, Message, MessageType
from ...plugins.harnesses import HarnessHistoryItem, HarnessHistoryKind
from ...utils.io_utils import run_sync_io

_HISTORY_BATCH_SIZE = 16


class HarnessSessionBridge:
    """Materialize third-party turns in the existing session format."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._locks = {}

    def _lock(self, session_id, user_id, channel):
        key = (session_id, user_id, channel)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def has_history(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        """Return whether QwenPaw already has a materialized transcript."""
        persisted = await self._session.get_session_state_dict(
            session_id,
            user_id,
            channel,
        )
        state = (persisted.get("agent") or {}).get("state") or {}
        return bool(state.get("context"))

    async def hydrate(self, *, session_id, user_id, channel, backend, history):
        async with self._lock(session_id, user_id, channel):
            await self._hydrate(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                backend=backend,
                history=history,
            )

    async def append_turn(self, *, request, response, backend):
        session_id = str(getattr(request, "session_id", "") or "default")
        user_id = str(getattr(request, "user_id", "") or session_id)
        channel = str(getattr(request, "channel", "") or "")
        async with self._lock(session_id, user_id, channel):
            await self._append_turn(
                request=request,
                response=response,
                backend=backend,
            )

    async def clear(self, *, session_id, user_id, channel):
        async with self._lock(session_id, user_id, channel):
            await self._clear(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )

    async def _hydrate(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        backend: str,
        history: list[HarnessHistoryItem],
    ) -> None:
        """Save recovered provider history when no QwenPaw context exists."""
        if not history or await self.has_history(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ):
            return
        state = AgentState().model_dump(mode="json")
        state["context"] = await self._materialize_history(history, backend)
        await self._session.import_session_history(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state={"agent": {"state": state}},
        )

    async def _append_turn(
        self,
        *,
        request: Any,
        response: AgentResponse,
        backend: str,
    ) -> None:
        """Append one request and its normalized output atomically."""
        session_id = str(getattr(request, "session_id", "") or "default")
        user_id = str(getattr(request, "user_id", "") or session_id)
        channel = str(getattr(request, "channel", "") or "")
        persisted = await self._session.get_session_state_dict(
            session_id,
            user_id,
            channel,
        )
        agent = persisted.get("agent")
        agent_data = dict(agent) if isinstance(agent, dict) else {}
        state = agent_data.get("state")
        if not isinstance(state, dict):
            state = AgentState().model_dump(mode="json")
        context = state.get("context")
        if not isinstance(context, list):
            context = []
        context.extend(self._request_messages(request, backend))
        context.extend(self._response_messages(response, backend))
        state["context"] = context

        proxy = StateProxy()
        agent_data["state"] = state
        proxy.data = agent_data
        request_context = getattr(request, "request_context", None) or {}
        turn_id = request_context.get(TRANSCRIPT_TURN_ID_CONTEXT_KEY)
        save = self._session.save_session_state
        options: dict[str, Any] = {}
        if turn_id and request_context.get(TRANSCRIPT_RECORDING_READY_KEY):
            save = self._session.save_turn_session_state
            options["turn_id"] = turn_id
            if TURN_COMMIT_KEY in request_context:
                options["pending_commit"] = request_context[TURN_COMMIT_KEY]
        await save(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
            **options,
        )

    async def _clear(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        turn_id: str | None = None,
    ) -> None:
        """Replace a materialized third-party transcript with empty state."""
        proxy = StateProxy()
        proxy.data = {"state": AgentState().model_dump(mode="json")}
        save = self._session.reset_session_state
        options: dict[str, Any] = {}
        if turn_id:
            save = self._session.save_turn_session_state
            options = {"turn_id": turn_id, "reset_context": True}
        await save(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
            **options,
        )

    @classmethod
    def _request_messages(
        cls,
        request: Any,
        backend: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in getattr(request, "input", None) or []:
            role = cls._enum_value(getattr(item, "role", None)) or "user"
            blocks = cls._content_blocks(getattr(item, "content", None))
            if not blocks:
                continue
            messages.append(
                cls._msg_dump(
                    name=role,
                    role=role,
                    content=blocks,
                    backend=backend,
                ),
            )
        return messages

    async def _materialize_history(
        self,
        history: list[HarnessHistoryItem],
        backend: str,
    ) -> list[dict[str, Any]]:
        """Convert a stable history order in bounded worker batches."""
        snapshot = list(history)
        messages: list[dict[str, Any]] = []
        for start in range(0, len(snapshot), _HISTORY_BATCH_SIZE):
            messages.extend(
                await run_sync_io(
                    self._history_messages,
                    snapshot[start : start + _HISTORY_BATCH_SIZE],
                    backend,
                ),
            )
        return messages

    @classmethod
    def _history_messages(
        cls,
        history: list[HarnessHistoryItem],
        backend: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in history:
            role = (
                "user" if item.kind == HarnessHistoryKind.USER else "assistant"
            )
            if item.kind == HarnessHistoryKind.REASONING:
                block = {"type": "thinking", "thinking": item.text}
            elif item.kind == HarnessHistoryKind.TOOL_CALL:
                arguments = item.data.get("arguments") or {}
                block = {
                    "type": "tool_call",
                    "id": item.item_id,
                    "name": item.tool_name or "tool",
                    "input": json.dumps(
                        arguments,
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            elif item.kind == HarnessHistoryKind.TOOL_OUTPUT:
                role = "assistant"
                block = {
                    "type": "tool_result",
                    "id": item.item_id,
                    "name": item.tool_name or "tool",
                    "output": item.text,
                }
            else:
                block = {"type": "text", "text": item.text}
            messages.append(
                cls._msg_dump(
                    name=role,
                    role=role,
                    content=[block],
                    backend=backend,
                    extra={"provider_item_id": item.item_id},
                ),
            )
        return messages

    @classmethod
    def _response_messages(
        cls,
        response: AgentResponse,
        backend: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in response.output:
            block = cls._output_block(item)
            if block is None:
                continue
            role = cls._enum_value(item.role) or "assistant"
            if role == "tool":
                role = "assistant"
            messages.append(
                cls._msg_dump(
                    name=role,
                    role=role,
                    content=[block],
                    backend=backend,
                    extra={
                        "response_id": response.id,
                        "message_id": item.id,
                        "status": cls._enum_value(item.status),
                    },
                ),
            )
        error = getattr(response, "error", None)
        if error and not messages:
            text = (
                str(error.get("message") or error)
                if isinstance(error, dict)
                else str(error)
            )
            messages.append(
                cls._msg_dump(
                    name="assistant",
                    role="assistant",
                    content=[{"type": "text", "text": text}],
                    backend=backend,
                    extra={"status": "failed"},
                ),
            )
        return messages

    @classmethod
    # pylint: disable=too-many-return-statements
    def _output_block(cls, message: Message) -> dict[str, Any] | None:
        content = message.content[0] if message.content else None
        if content is None:
            return None
        message_type = cls._enum_value(message.type)
        if message_type == MessageType.MESSAGE.value:
            return {
                "type": "text",
                "text": str(getattr(content, "text", "") or ""),
            }
        if message_type == MessageType.REASONING.value:
            return {
                "type": "thinking",
                "thinking": str(getattr(content, "text", "") or ""),
            }
        data = getattr(content, "data", None)
        if not isinstance(data, dict):
            return None
        if message_type == MessageType.PLUGIN_CALL.value:
            return {
                "type": "tool_call",
                "id": str(data.get("call_id") or message.id),
                "name": str(data.get("name") or "tool"),
                "input": str(data.get("arguments") or "{}"),
            }
        if message_type == MessageType.PLUGIN_CALL_OUTPUT.value:
            output = data.get("output")
            if isinstance(output, (dict, list)):
                output = json.dumps(output, ensure_ascii=False)
            return {
                "type": "tool_result",
                "id": str(data.get("call_id") or message.id),
                "name": str(data.get("name") or "tool"),
                "output": str(output or ""),
            }
        return None

    @staticmethod
    def _content_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        blocks: list[dict[str, Any]] = []
        for item in content or []:
            text = getattr(item, "text", None)
            if text:
                blocks.append({"type": "text", "text": str(text)})
                continue
            content_type = HarnessSessionBridge._enum_value(
                getattr(item, "type", None),
            )
            field_by_type = {
                "image": "image_url",
                "audio": "data",
                "video": "video_url",
                "file": "file_url",
            }
            field = field_by_type.get(content_type)
            source = getattr(item, field, None) if field else None
            if not source:
                continue
            source_text = str(source)
            if "://" not in source_text and not source_text.startswith(
                "data:",
            ):
                source_text = (
                    Path(source_text).expanduser().absolute().as_uri()
                )
            default_media_types = {
                "image": "image/png",
                "audio": "audio/mpeg",
                "video": "video/mp4",
                "file": "application/octet-stream",
            }
            media_type = (
                mimetypes.guess_type(str(source))[0]
                or default_media_types[content_type]
            )
            block: dict[str, Any] = {
                "type": "data",
                "source": {
                    "type": "url",
                    "url": source_text,
                    "media_type": media_type,
                },
            }
            if content_type == "file":
                block["name"] = getattr(item, "filename", None)
            blocks.append(block)
        return blocks

    @staticmethod
    def _msg_dump(
        *,
        name: str,
        role: str,
        content: list[dict[str, Any]],
        backend: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {"third_party_backend": backend}
        metadata.update(extra or {})
        message = Msg(
            name=name,
            role=role,
            content=content,
            metadata=metadata,
        )
        return message.model_dump(mode="json")

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")


__all__ = ["HarnessSessionBridge"]
