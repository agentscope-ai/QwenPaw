# -*- coding: utf-8 -*-
"""Push-based runtime status persistence for chat sessions."""
from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from .models import ChatRuntimeStatus, ChatRuntimeStatusBreakdownItem

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_WINDOW = 32768
DEFAULT_RESERVED_RESPONSE_TOKENS = 2048
_CONTEXT_WINDOW_KEYS = (
    "context_length",
    "context_window",
    "max_context_tokens",
    "num_ctx",
    "n_ctx",
    "ctx_len",
)
_RESERVED_RESPONSE_KEYS = ("max_tokens", "max_output_tokens")
_FILE_BLOCK_TYPES = {"file", "image", "audio", "video"}
_TOOL_BLOCK_TYPES = {"tool_use", "tool_result"}


@dataclass(slots=True)
class RuntimeStatusWriteContext:
    session: Any
    agent_id: str
    session_id: str
    user_id: str
    chat_id: str


_current_runtime_status_context: ContextVar[RuntimeStatusWriteContext | None] = (
    ContextVar("current_runtime_status_context", default=None)
)


def set_current_runtime_status_context(
    context: RuntimeStatusWriteContext,
) -> Token[RuntimeStatusWriteContext | None]:
    return _current_runtime_status_context.set(context)


def reset_current_runtime_status_context(
    token: Token[RuntimeStatusWriteContext | None],
) -> None:
    _current_runtime_status_context.reset(token)


def get_current_runtime_status_context() -> RuntimeStatusWriteContext | None:
    return _current_runtime_status_context.get()


def _get_number_record_value(
    record: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> int | None:
    for key in keys:
        raw = (record or {}).get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            value = int(raw)
            if value > 0:
                return value
        if isinstance(raw, str):
            try:
                value = int(float(raw))
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def clamp_ratio(tokens: int, window_tokens: int) -> float:
    if window_tokens <= 0:
        return 0
    return min(1.0, max(0.0, float(tokens) / float(window_tokens)))


def resolve_reserved_response_tokens(provider) -> int:
    return (
        _get_number_record_value(
            getattr(provider, "generate_kwargs", None),
            _RESERVED_RESPONSE_KEYS,
        )
        or DEFAULT_RESERVED_RESPONSE_TOKENS
    )


def resolve_context_window_tokens(
    provider,
    running_config,
    reserved_response_tokens: int,
) -> int:
    configured = _get_number_record_value(
        getattr(provider, "generate_kwargs", None),
        _CONTEXT_WINDOW_KEYS,
    )
    if configured:
        return configured

    max_input_length = getattr(running_config, "max_input_length", 0)
    if isinstance(max_input_length, int) and max_input_length > 0:
        safety_margin = max(1024, int(max_input_length * 0.1))
        return max_input_length + reserved_response_tokens + safety_margin
    return DEFAULT_CONTEXT_WINDOW


def build_empty_runtime_status(
    *,
    agent_id: str | None,
    session_id: str | None,
    user_id: str | None,
    chat_id: str | None,
    context_window_tokens: int,
    reserved_response_tokens: int,
    model_id: str | None,
    provider_id: str | None,
    profile_label: str,
) -> ChatRuntimeStatus:
    return ChatRuntimeStatus(
        scope_level="chat",
        snapshot_source="empty_baseline",
        snapshot_stage="pre_model_call",
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        chat_id=chat_id,
        context_window_tokens=context_window_tokens,
        used_tokens=0,
        used_ratio=0,
        reserved_response_tokens=reserved_response_tokens,
        remaining_tokens=max(0, context_window_tokens - reserved_response_tokens),
        model_id=model_id,
        provider_id=provider_id,
        profile_label=profile_label,
        breakdown=[
            ChatRuntimeStatusBreakdownItem(
                key="system-instructions",
                label="System Instructions",
                tokens=0,
                ratio=0,
                section="system",
            ),
            ChatRuntimeStatusBreakdownItem(
                key="tool-definitions",
                label="Tool Definitions",
                tokens=0,
                ratio=0,
                section="system",
            ),
            ChatRuntimeStatusBreakdownItem(
                key="messages",
                label="Messages",
                tokens=0,
                ratio=0,
                section="user",
            ),
            ChatRuntimeStatusBreakdownItem(
                key="tool-results",
                label="Tool Results",
                tokens=0,
                ratio=0,
                section="user",
            ),
            ChatRuntimeStatusBreakdownItem(
                key="files",
                label="Files",
                tokens=0,
                ratio=0,
                section="user",
            ),
        ],
    )


def _classify_bucket(message: dict[str, Any]) -> str:
    role = str(message.get("role", "") or "").lower()
    content = message.get("content")
    block_types: set[str] = set()
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                block_types.add(str(block.get("type", "") or ""))

    if block_types & _FILE_BLOCK_TYPES:
        return "files"
    if role == "tool" or block_types & _TOOL_BLOCK_TYPES or message.get("tool_calls"):
        return "tool-results"
    return "messages"


class RuntimeStatusRecorder:
    def __init__(
        self,
        *,
        token_counter,
        context_window_tokens: int,
        reserved_response_tokens: int,
        provider_id: str | None,
        model_id: str | None,
        profile_label: str,
    ) -> None:
        self._token_counter = token_counter
        self._context_window_tokens = context_window_tokens
        self._reserved_response_tokens = reserved_response_tokens
        self._provider_id = provider_id
        self._model_id = model_id
        self._profile_label = profile_label

    async def build_snapshot(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatRuntimeStatus:
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        system_instructions_tokens = 0
        tool_definitions_tokens = 0
        if system_messages:
            system_instructions_tokens = await self._token_counter.count(system_messages)
            with_tools_tokens = await self._token_counter.count(
                system_messages,
                tools=tools or None,
            )
            tool_definitions_tokens = max(0, with_tools_tokens - system_instructions_tokens)
        elif tools:
            tool_definitions_tokens = await self._token_counter.count([], tools=tools)

        category_totals = {
            "messages": 0,
            "tool-results": 0,
            "files": 0,
        }
        for message in messages:
            if message.get("role") == "system":
                continue
            bucket = _classify_bucket(message)
            category_totals[bucket] += await self._token_counter.count([message])

        used_tokens = (
            system_instructions_tokens
            + tool_definitions_tokens
            + category_totals["messages"]
            + category_totals["tool-results"]
            + category_totals["files"]
        )

        return ChatRuntimeStatus(
            scope_level="chat",
            snapshot_source="runtime_push",
            snapshot_stage="pre_model_call",
            agent_id=None,
            session_id=None,
            user_id=None,
            chat_id=None,
            context_window_tokens=self._context_window_tokens,
            used_tokens=used_tokens,
            used_ratio=clamp_ratio(used_tokens, self._context_window_tokens),
            reserved_response_tokens=self._reserved_response_tokens,
            remaining_tokens=max(
                0,
                self._context_window_tokens - used_tokens - self._reserved_response_tokens,
            ),
            model_id=self._model_id,
            provider_id=self._provider_id,
            profile_label=self._profile_label,
            breakdown=[
                ChatRuntimeStatusBreakdownItem(
                    key="system-instructions",
                    label="System Instructions",
                    tokens=system_instructions_tokens,
                    ratio=clamp_ratio(system_instructions_tokens, self._context_window_tokens),
                    section="system",
                ),
                ChatRuntimeStatusBreakdownItem(
                    key="tool-definitions",
                    label="Tool Definitions",
                    tokens=tool_definitions_tokens,
                    ratio=clamp_ratio(tool_definitions_tokens, self._context_window_tokens),
                    section="system",
                ),
                ChatRuntimeStatusBreakdownItem(
                    key="messages",
                    label="Messages",
                    tokens=category_totals["messages"],
                    ratio=clamp_ratio(category_totals["messages"], self._context_window_tokens),
                    section="user",
                ),
                ChatRuntimeStatusBreakdownItem(
                    key="tool-results",
                    label="Tool Results",
                    tokens=category_totals["tool-results"],
                    ratio=clamp_ratio(category_totals["tool-results"], self._context_window_tokens),
                    section="user",
                ),
                ChatRuntimeStatusBreakdownItem(
                    key="files",
                    label="Files",
                    tokens=category_totals["files"],
                    ratio=clamp_ratio(category_totals["files"], self._context_window_tokens),
                    section="user",
                ),
            ],
        )

    async def record(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        snapshot = await self.build_snapshot(messages=messages, tools=tools)
        await persist_runtime_status(snapshot)


async def persist_runtime_status(snapshot: ChatRuntimeStatus) -> None:
    context = get_current_runtime_status_context()
    if context is None:
        return
    try:
        owned_snapshot = snapshot.model_copy(
            update={
                "scope_level": "chat",
                "snapshot_source": snapshot.snapshot_source or "runtime_push",
                "snapshot_stage": snapshot.snapshot_stage or "pre_model_call",
                "agent_id": context.agent_id,
                "session_id": context.session_id,
                "user_id": context.user_id,
                "chat_id": context.chat_id,
            }
        )
        await context.session.update_session_state(
            session_id=context.session_id,
            user_id=context.user_id,
            key="runtime_status",
            value={
                "chat_id": context.chat_id,
                "snapshot": owned_snapshot.model_dump(mode="json"),
            },
        )
    except Exception:
        logger.warning(
            "Failed to persist runtime status for session_id=%s user_id=%s",
            context.session_id,
            context.user_id,
            exc_info=True,
        )


async def load_persisted_runtime_status(
    session,
    *,
    session_id: str,
    user_id: str,
    chat_id: str,
) -> ChatRuntimeStatus | None:
    state = await session.get_session_state_dict(session_id, user_id)
    payload = state.get("runtime_status")
    if not isinstance(payload, dict):
        return None
    stored_chat_id = str(payload.get("chat_id") or "")
    if stored_chat_id and stored_chat_id != chat_id:
        return None
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    try:
        return ChatRuntimeStatus.model_validate(snapshot)
    except Exception:
        logger.warning(
            "Invalid persisted runtime status for session_id=%s user_id=%s",
            session_id,
            user_id,
            exc_info=True,
        )
        return None