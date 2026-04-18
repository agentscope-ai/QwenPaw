# -*- coding: utf-8 -*-
"""Minimal high-level ACP service."""
from __future__ import annotations

import asyncio
import atexit
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .core import (
    ACPAgentConfig,
    ACPConfig,
    ACPConfigurationError,
    ACPSessionError,
)
from .permissions import ACPPermissionAdapter
from .runtime import ACPRuntime

MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]
PermissionHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class _Conversation:
    chat_id: str
    agent: str
    acp_session_id: str
    cwd: str
    runtime: ACPRuntime


class ACPService:
    def __init__(self, *, config: ACPConfig):
        self.config = config
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], _Conversation] = {}

    def _build_permission_handler(
        self,
        *,
        agent: str,
        cwd: str,
    ) -> tuple[ACPPermissionAdapter, PermissionHandler]:
        permission_adapter = ACPPermissionAdapter(cwd=cwd)

        async def _resolve_permission(payload: dict[str, Any]) -> Any:
            return await permission_adapter.resolve_permission(
                agent=agent,
                request_payload=payload,
            )

        return permission_adapter, _resolve_permission

    async def run_turn(
        self,
        *,
        chat_id: str,
        agent: str,
        prompt_blocks: list[dict[str, Any]],
        cwd: str,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        conversation = await self._get_or_start_session(
            chat_id=chat_id,
            agent=agent,
            cwd=cwd,
        )
        _, permission_handler = self._build_permission_handler(
            agent=agent,
            cwd=conversation.cwd,
        )

        result_payload = await conversation.runtime.prompt(
            session_id=conversation.acp_session_id,
            prompt_blocks=prompt_blocks,
            permission_handler=permission_handler,
            on_message=on_message,
        )
        return {
            "suspended_permission": conversation.runtime.suspended_permission,
            "result": result_payload,
        }

    async def resume_permission(
        self,
        *,
        acp_session_id: str,
        option_id: str,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        conversation = await self._find_session_by_acp_id(acp_session_id)
        if conversation is None:
            raise ACPSessionError(f"Session not found: {acp_session_id}")
        if conversation.runtime.suspended_permission is None:
            raise ACPSessionError(
                f"Session {acp_session_id} has no pending permission request",
            )

        suspended = conversation.runtime.suspended_permission
        (
            permission_adapter,
            permission_handler,
        ) = self._build_permission_handler(
            agent=conversation.agent,
            cwd=conversation.cwd,
        )
        selected_option = permission_adapter.resolve_option_by_id(
            suspended.options,
            option_id,
        )
        if selected_option is None:
            raise ACPSessionError(f"Unknown option_id '{option_id}'")
        permission_result = permission_adapter.selected_result(selected_option)

        result_payload = (
            await conversation.runtime.resume_prompt_after_permission(
                permission_result=permission_result,
                on_message=on_message,
                permission_handler=permission_handler,
            )
        )
        return {
            "suspended_permission": conversation.runtime.suspended_permission,
            "result": result_payload,
        }

    async def close_chat_session(self, *, chat_id: str, agent: str) -> None:
        async with self._lock:
            conversation = self._sessions.pop((chat_id, agent), None)
        if conversation is not None:
            try:
                await conversation.runtime.close()
            except Exception:
                pass

    async def close_all_sessions(self) -> None:
        async with self._lock:
            conversations = list(self._sessions.values())
            self._sessions.clear()
        for conversation in conversations:
            try:
                await conversation.runtime.close()
            except Exception:
                pass

    async def get_session(
        self,
        chat_id: str,
        agent: str,
    ) -> _Conversation | None:
        async with self._lock:
            return self._sessions.get((chat_id, agent))

    async def get_pending_permission(
        self,
        *,
        chat_id: str,
        agent: str,
    ) -> Any | None:
        conversation = await self.get_session(chat_id, agent)
        if conversation is None:
            return None
        return conversation.runtime.suspended_permission

    async def _get_or_start_session(
        self,
        *,
        chat_id: str,
        agent: str,
        cwd: str,
    ) -> _Conversation:
        agent_config = self._get_agent_config(agent)
        async with self._lock:
            existing = self._sessions.get((chat_id, agent))

        if existing is not None and existing.runtime.transport.is_running():
            return existing

        session_cwd = cwd or (existing.cwd if existing is not None else ".")
        runtime = ACPRuntime(agent, agent_config)
        await runtime.start(session_cwd)

        if existing is None:
            conversation = _Conversation(
                chat_id=chat_id,
                agent=agent,
                acp_session_id=await runtime.new_session(session_cwd),
                cwd=session_cwd,
                runtime=runtime,
            )
        else:
            existing.runtime = runtime
            existing.acp_session_id = await runtime.load_session(
                existing.acp_session_id,
                existing.cwd,
            )
            conversation = existing

        async with self._lock:
            self._sessions[(chat_id, agent)] = conversation
        return conversation

    async def _find_session_by_acp_id(
        self,
        acp_session_id: str,
    ) -> _Conversation | None:
        async with self._lock:
            for session in self._sessions.values():
                if session.acp_session_id == acp_session_id:
                    return session
        return None

    def _get_agent_config(self, agent: str) -> ACPAgentConfig:
        agent_config = self.config.agents.get(agent)
        if agent_config is None:
            raise ACPConfigurationError(
                f"Unknown ACP agent: {agent}",
                agent=agent,
            )
        if not agent_config.enabled:
            raise ACPConfigurationError(
                f"ACP agent '{agent}' is disabled",
                agent=agent,
            )
        return agent_config


_acp_service: ACPService | None = None


def get_acp_service() -> ACPService | None:
    return _acp_service


def _atexit_cleanup() -> None:
    if _acp_service is None:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() or loop.is_closed():
            return
        loop.run_until_complete(_acp_service.close_all_sessions())
    except Exception:
        pass


atexit.register(_atexit_cleanup)


def init_acp_service(config: ACPConfig) -> ACPService:
    global _acp_service
    previous_service = _acp_service
    _acp_service = ACPService(config=config)
    if previous_service is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
        if loop is not None and not loop.is_closed():
            if loop.is_running():
                loop.create_task(previous_service.close_all_sessions())
            else:
                loop.run_until_complete(previous_service.close_all_sessions())
    return _acp_service
