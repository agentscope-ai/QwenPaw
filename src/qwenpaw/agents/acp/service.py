# -*- coding: utf-8 -*-
"""High-level ACP service built on the official Python SDK."""
from __future__ import annotations

import asyncio
import atexit
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
from acp.schema import ClientCapabilities, Implementation

from .client import ACPHostedClient
from .core import ACPAgentConfig, ACPConfig, ACPConfigurationError, ACPSessionError

MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]


@dataclass
class _Conversation:
    chat_id: str
    agent: str
    acp_session_id: str
    cwd: str
    conn: Any
    process: Any
    client: ACPHostedClient
    exit_stack: AsyncExitStack
    turn_lock: asyncio.Lock
    prompt_task: asyncio.Task | None = None


class ACPService:
    def __init__(self, *, config: ACPConfig):
        self.config = config
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], _Conversation] = {}

    async def run_turn(
        self,
        *,
        chat_id: str,
        agent: str,
        prompt_blocks: list[dict[str, Any]],
        cwd: str,
        on_message: MessageHandler,
        restart: bool = False,
        require_existing: bool = False,
    ) -> dict[str, Any]:
        if restart:
            await self.close_chat_session(chat_id=chat_id, agent=agent)

        conversation = await self._get_or_create_session(
            chat_id=chat_id,
            agent=agent,
            cwd=cwd,
            require_existing=require_existing,
        )
        async with conversation.turn_lock:
            if conversation.client.pending_permission is not None:
                raise ACPSessionError(
                    f"Session {conversation.acp_session_id} is waiting for permission",
                )
            if conversation.prompt_task is not None and not conversation.prompt_task.done():
                raise ACPSessionError(
                    f"Session {conversation.acp_session_id} is already processing a turn",
                )

            conversation.cwd = cwd or conversation.cwd
            conversation.client.update_cwd(conversation.cwd)
            conversation.client.start_prompt(on_message)
            conversation.prompt_task = asyncio.create_task(
                conversation.conn.prompt(
                    session_id=conversation.acp_session_id,
                    prompt=self._prompt_blocks_to_models(prompt_blocks),
                ),
            )
            return await self._wait_for_prompt_outcome(
                conversation=conversation,
                on_message=on_message,
            )

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
        if conversation.client.pending_permission is None:
            raise ACPSessionError(
                f"Session {acp_session_id} has no pending permission request",
            )
        if conversation.prompt_task is None or conversation.prompt_task.done():
            raise ACPSessionError(
                f"Session {acp_session_id} is not awaiting permission resume",
            )

        async with conversation.turn_lock:
            conversation.client.resume_prompt(on_message)
            conversation.client.resolve_permission(option_id)
            await conversation.client.emit_permission_resolved()
            return await self._wait_for_prompt_outcome(
                conversation=conversation,
                on_message=on_message,
            )

    async def close_chat_session(self, *, chat_id: str, agent: str) -> None:
        async with self._lock:
            conversation = self._sessions.pop((chat_id, agent), None)
        if conversation is not None:
            await self._close_conversation(conversation)

    async def close_all_sessions(self) -> None:
        async with self._lock:
            conversations = list(self._sessions.values())
            self._sessions.clear()
        for conversation in conversations:
            await self._close_conversation(conversation)

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
        return conversation.client.pending_permission

    async def cancel_turn(self, *, chat_id: str, agent: str) -> bool:
        conversation = await self.get_session(chat_id, agent)
        if conversation is None:
            return False

        prompt_task = conversation.prompt_task
        if prompt_task is None or prompt_task.done():
            return False

        for _ in range(3):
            try:
                await conversation.conn.cancel(
                    session_id=conversation.acp_session_id,
                )
            except Exception:
                return False

            try:
                await asyncio.wait_for(
                    asyncio.shield(prompt_task),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                if prompt_task.done():
                    break
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                break
            else:
                break

        return prompt_task.done()

    async def _get_or_create_session(
        self,
        *,
        chat_id: str,
        agent: str,
        cwd: str,
        require_existing: bool,
    ) -> _Conversation:
        agent_config = self._get_agent_config(agent)
        async with self._lock:
            existing = self._sessions.get((chat_id, agent))

        if existing is not None:
            if existing.process.returncode is None:
                return existing
            await self.close_chat_session(chat_id=chat_id, agent=agent)
            if require_existing:
                raise ACPSessionError(
                    f"ACP session for runner '{agent}' is no longer active; call start first",
                )
        elif require_existing:
            raise ACPSessionError(
                f"no bound ACP session found for runner '{agent}' in current chat",
            )

        session_cwd = cwd or "."
        conversation = await self._open_conversation(
            chat_id=chat_id,
            agent=agent,
            cwd=session_cwd,
            agent_config=agent_config,
        )

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

    async def _open_conversation(
        self,
        *,
        chat_id: str,
        agent: str,
        cwd: str,
        agent_config: ACPAgentConfig,
    ) -> _Conversation:
        client = ACPHostedClient(
            agent_name=agent,
            agent_config=agent_config,
            cwd=cwd,
        )
        exit_stack = AsyncExitStack()
        try:
            conn, process = await exit_stack.enter_async_context(
                spawn_agent_process(
                    client,
                    agent_config.command,
                    *agent_config.args,
                    cwd=cwd,
                    env={**os.environ, **agent_config.env},
                    transport_kwargs={
                        "limit": agent_config.stdio_buffer_limit_bytes,
                    },
                ),
            )
            initialized = await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="qwenpaw-acp-service",
                    version="0.1.0",
                ),
            )
            if initialized.protocol_version != PROTOCOL_VERSION:
                raise ACPSessionError(
                    f"Protocol mismatch: {initialized.protocol_version}",
                )
            new_session = await conn.new_session(cwd=cwd)
            return _Conversation(
                chat_id=chat_id,
                agent=agent,
                acp_session_id=new_session.session_id,
                cwd=cwd,
                conn=conn,
                process=process,
                client=client,
                exit_stack=exit_stack,
                turn_lock=asyncio.Lock(),
            )
        except Exception:
            await exit_stack.aclose()
            raise

    async def _wait_for_prompt_outcome(
        self,
        *,
        conversation: _Conversation,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        del on_message
        prompt_task = conversation.prompt_task
        if prompt_task is None:
            raise ACPSessionError("ACP prompt task is missing")

        permission_task = asyncio.create_task(
            conversation.client.wait_for_permission_request(),
        )
        try:
            done, pending = await asyncio.wait(
                {prompt_task, permission_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if permission_task in done and conversation.client.pending_permission is not None:
                finished_event = await conversation.client.finish_prompt()
                return {
                    "status": "permission_required",
                    "suspended_permission": conversation.client.pending_permission,
                    "event": finished_event,
                }

            permission_task.cancel()
            try:
                await permission_task
            except asyncio.CancelledError:
                pass

            try:
                await prompt_task
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                conversation.prompt_task = None
                await conversation.client.finish_prompt()
                raise ACPSessionError(str(exc)) from exc

            conversation.prompt_task = None
            finished_event = await conversation.client.finish_prompt()
            pending_permission = conversation.client.pending_permission
            if pending_permission is not None:
                return {
                    "status": "permission_required",
                    "suspended_permission": pending_permission,
                    "event": finished_event,
                }
            return {"status": "completed", "event": finished_event}
        finally:
            if not permission_task.done():
                permission_task.cancel()
                try:
                    await permission_task
                except asyncio.CancelledError:
                    pass

    async def _close_conversation(self, conversation: _Conversation) -> None:
        try:
            if conversation.prompt_task is not None and not conversation.prompt_task.done():
                conversation.prompt_task.cancel()
                try:
                    await conversation.prompt_task
                except Exception:
                    pass
        finally:
            await conversation.exit_stack.aclose()

    @staticmethod
    def _prompt_blocks_to_models(blocks: list[dict[str, Any]]) -> list[Any]:
        prompt_models: list[Any] = []
        for block in blocks:
            if block.get("type") != "text":
                raise ACPConfigurationError(
                    "Only text prompt blocks are currently supported",
                )
            prompt_models.append(text_block(str(block.get("text", ""))))
        return prompt_models


_acp_services: dict[str, ACPService] = {}


def get_acp_service(agent_id: str | None = None) -> ACPService | None:
    if agent_id is None:
        return None
    return _acp_services.get(agent_id)


def init_acp_service(agent_id: str, config: ACPConfig) -> ACPService:
    previous_service = _acp_services.get(agent_id)
    _acp_services[agent_id] = ACPService(config=config)
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
    return _acp_services[agent_id]


def close_acp_service(agent_id: str) -> None:
    previous_service = _acp_services.pop(agent_id, None)
    if previous_service is None:
        return
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


def _shutdown_acp_services() -> None:
    services = list(_acp_services.values())
    _acp_services.clear()
    if not services:
        return
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            for service in services:
                loop.create_task(service.close_all_sessions())
            return
    except RuntimeError:
        pass
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            asyncio.gather(*(service.close_all_sessions() for service in services)),
        )
        loop.close()
    except Exception:
        pass


atexit.register(_shutdown_acp_services)
