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
                    env=self._build_env(agent_config),
                    cwd=cwd,
                ),
            )
            await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="QwenPaw",
                    title="QwenPaw",
                    version="1.0.0",
                ),
            )
            session = await conn.new_session(cwd=cwd, mcp_servers=[])
            return _Conversation(
                chat_id=chat_id,
                agent=agent,
                acp_session_id=session.session_id,
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
        if conversation.prompt_task is None:
            raise ACPSessionError(
                f"Session {conversation.acp_session_id} has no active prompt task",
            )

        while True:
            permission_wait_task = asyncio.create_task(
                conversation.client.wait_for_permission_request(),
            )
            done, _ = await asyncio.wait(
                {conversation.prompt_task, permission_wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if permission_wait_task in done:
                if conversation.client.pending_permission is not None:
                    return {
                        "suspended_permission": conversation.client.pending_permission,
                        "result": None,
                    }
            else:
                permission_wait_task.cancel()
                try:
                    await permission_wait_task
                except (asyncio.CancelledError, Exception):
                    pass

            if conversation.prompt_task in done:
                prompt_task = conversation.prompt_task
                conversation.prompt_task = None
                prompt_response = await prompt_task
                await conversation.client.flush_assistant_text()
                result_payload = prompt_response.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
                await on_message(
                    {
                        "type": "status",
                        "status": "run_finished",
                        "result": result_payload,
                    },
                    True,
                )
                return {
                    "suspended_permission": None,
                    "result": result_payload,
                }

            permission_wait_task.cancel()
            try:
                await permission_wait_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _close_conversation(self, conversation: _Conversation) -> None:
        prompt_task = conversation.prompt_task
        conversation.prompt_task = None
        if prompt_task is not None and not prompt_task.done():
            prompt_task.cancel()
            try:
                await prompt_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await conversation.exit_stack.aclose()
        except Exception:
            pass

    def _build_env(self, agent_config: ACPAgentConfig) -> dict[str, str]:
        env = dict(os.environ)
        env.update(agent_config.env)
        return env

    def _prompt_blocks_to_models(self, prompt_blocks: list[dict[str, Any]]) -> list[Any]:
        result: list[Any] = []
        for block in prompt_blocks:
            if not isinstance(block, dict):
                raise ACPSessionError("ACP prompt block must be a dict")
            block_type = str(block.get("type") or "").strip().lower()
            if block_type != "text":
                raise ACPSessionError(
                    f"Unsupported ACP prompt block type: {block_type or '<empty>'}",
                )
            result.append(text_block(str(block.get("text") or "")))
        return result


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
