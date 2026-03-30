# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.schemas.exception import AgentException
from dotenv import load_dotenv

from .command_dispatch import (
    _get_last_user_text,
    _is_command,
    run_command_path,
)
from .query_error_dump import write_query_error_dump
from .session import SafeJSONSession
from .utils import build_env_context
from ..channels.schema import DEFAULT_CHANNEL
from ...agents.react_agent import CoPawAgent
from ...security.tool_guard.models import TOOL_GUARD_DENIED_MARK
from ...config.config import load_agent_config
from ...config import load_config
from ...constant import (
    ACP_DRAIN_MAX_ATTEMPTS,
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    WORKING_DIR,
)
from ...security.tool_guard.approval import ApprovalDecision
from ...acp import (
    ACPConfigurationError,
    ACPService,
    ExternalAgentConfig,
    encode_runtime_i18n_text,
    merge_external_agent_configs,
    parse_external_agent_config,
    parse_external_agent_text,
)
from ...acp.permissions import build_prompt_approval_artifacts
from ...acp.policy import is_obviously_dangerous_prompt, prompt_blocks_to_text

if TYPE_CHECKING:
    from ...agents.memory import BaseMemoryManager

logger = logging.getLogger(__name__)

_APPROVE_EXACT = frozenset(
    {
        "approve",
        "/approve",
        "/daemon approve",
    },
)


def _is_approval(text: str) -> bool:
    """Return True only when *text* is exactly ``approve``,
    ``/approve``, or ``/daemon approve`` (case-insensitive).

    Leading/trailing whitespace and blank lines are stripped before
    comparison.  Everything else is treated as denial.
    """
    normalized = " ".join(text.split()).lower()
    return normalized in _APPROVE_EXACT


class AgentRunner(Runner):
    def __init__(
        self,
        agent_id: str = "default",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
    ) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self.agent_id = agent_id  # Store agent_id for config loading
        self.workspace_dir = (
            workspace_dir  # Store workspace_dir for prompt building
        )
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self._workspace: Any = None  # Workspace instance for control commands
        self.memory_manager: BaseMemoryManager | None = None
        self._task_tracker = task_tracker  # Task tracker for background tasks
        self._acp_service: ACPService | None = None

    def set_chat_manager(self, chat_manager):
        """Set chat manager for auto-registration.

        Args:
            chat_manager: ChatManager instance
        """
        self._chat_manager = chat_manager

    def set_mcp_manager(self, mcp_manager):
        """Set MCP client manager for hot-reload support.

        Args:
            mcp_manager: MCPClientManager instance
        """
        self._mcp_manager = mcp_manager

    def set_workspace(self, workspace):
        """Set workspace for control command handlers.

        Args:
            workspace: Workspace instance
        """
        self._workspace = workspace

    def _get_acp_service(self) -> ACPService:
        """Return the lazily-created ACP service."""
        config = load_config()
        if self._acp_service is None or self._acp_service.config != config.acp:
            self._acp_service = ACPService(config=config.acp)
        return self._acp_service

    def _build_external_prompt_blocks(
        self,
        msgs,
        text_override: str | None = None,
    ) -> list[dict[str, str]]:
        """Convert the final user message into ACP prompt blocks."""
        if text_override is not None:
            return [{"type": "text", "text": text_override}]

        query = _get_last_user_text(msgs) or ""
        return [{"type": "text", "text": query}]

    @staticmethod
    def _resolve_external_agent_keep_session(
        external_agent,
        acp_config,
    ) -> bool:
        """Resolve keep-session using request/text overrides first.

        Priority:
        1. Request explicit keep_session
        2. Text-parsed keep_session
        3. Per-harness config default
        4. False
        """
        if getattr(external_agent, "keep_session_specified", False):
            return bool(external_agent.keep_session)

        harnesses = getattr(acp_config, "harnesses", None)
        if isinstance(harnesses, dict):
            harness_cfg = harnesses.get(external_agent.harness)
            if harness_cfg is not None:
                return bool(
                    getattr(harness_cfg, "keep_session_default", False),
                )

        return False

    @staticmethod
    def _restore_external_agent_from_chat_meta(
        external_agent: ExternalAgentConfig | None,
        chat: Any | None,
        query: str | None,
    ) -> ExternalAgentConfig | None:
        """Recover ACP routing from chat metadata for keep-session chats.

        When the frontend sends a plain follow-up message, it currently does
        not include the bound ``external_agent`` payload again. If the chat is
        already pinned to a keep-session ACP harness, restore that binding so
        the next turn continues the same ACP conversation instead of falling
        back to the normal CoPaw agent path.
        """
        if external_agent is not None or chat is None:
            return external_agent

        chat_meta = dict(getattr(chat, "meta", {}) or {})
        external_meta = dict(chat_meta.get("external_agent") or {})
        if not external_meta.get("enabled", True):
            return None

        harness = str(external_meta.get("harness") or "").strip()
        acp_session_id = str(external_meta.get("acp_session_id") or "").strip()
        if not harness or not acp_session_id:
            return None
        if not bool(external_meta.get("keep_session")):
            return None

        return ExternalAgentConfig(
            enabled=True,
            harness=harness,
            keep_session=True,
            cwd=external_meta.get("cwd"),
            existing_session_id=acp_session_id,
            prompt=query,
            keep_session_specified=True,
        )

    async def _append_external_agent_history(
        self,
        *,
        session_id: str,
        user_id: str,
        messages: list[Msg],
    ) -> None:
        """Persist ACP turns into a dedicated session memory slot."""
        if not session_id or self.session is None or not messages:
            return

        coalesced_messages: list[Msg] = []
        for message in messages:
            if (
                coalesced_messages
                and getattr(coalesced_messages[-1], "id", None)
                == getattr(message, "id", None)
                and coalesced_messages[-1].role == message.role
            ):
                coalesced_messages[-1] = copy.deepcopy(message)
            else:
                coalesced_messages.append(copy.deepcopy(message))

        state = await self.session.get_session_state_dict(
            session_id,
            user_id,
        )
        history_state = state.get("external_agent_memory", {})
        memory = InMemoryMemory()

        if isinstance(history_state, dict):
            try:
                memory.load_state_dict(history_state, strict=False)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to load ACP history for session %s",
                    session_id,
                    exc_info=True,
                )

        await memory.add(coalesced_messages)
        await self.session.update_session_state(
            session_id,
            "external_agent_memory",
            memory.state_dict(),
            user_id=user_id,
            create_if_not_exist=True,
        )

    _APPROVAL_TIMEOUT_SECONDS = TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS

    async def _resolve_pending_approval(
        self,
        session_id: str,
        query: str | None,
    ) -> tuple[
        Msg | None,
        bool,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        """Check for a pending tool-guard approval for *session_id*.

        Returns ``(response_msg, was_consumed, approved_tool_call,
        approved_external_agent_request)``:

        - ``(None, False, None, None)`` — no pending approval.
        - ``(Msg, True, None, None)``   — denied; yield the Msg and stop.
        - ``(None, True, dict, None)``  — approved normal tool replay.
        - ``(None, True, None, dict)``  — approved ACP prompt replay.

        Approvals are resolved FIFO per session (oldest pending first).
        """
        if not session_id:
            return None, False, None, None

        from ..approvals import get_approval_service

        svc = get_approval_service()
        pending = await svc.get_pending_by_session(session_id)
        if pending is None:
            return None, False, None, None

        elapsed = time.time() - pending.created_at
        if elapsed > self._APPROVAL_TIMEOUT_SECONDS:
            await svc.resolve_request(
                pending.request_id,
                ApprovalDecision.TIMEOUT,
            )
            return (
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text=encode_runtime_i18n_text(
                                "acp.approval.chat.timeout",
                                {
                                    "toolName": pending.tool_name,
                                    "seconds": int(elapsed),
                                },
                            ),
                        ),
                    ],
                ),
                True,
                None,
                None,
            )

        normalized = (query or "").strip().lower()
        if _is_approval(normalized):
            resolved = await svc.resolve_request(
                pending.request_id,
                ApprovalDecision.APPROVED,
            )
            approved_tool_call: dict[str, Any] | None = None
            approved_external_agent_request: dict[str, Any] | None = None
            record = resolved or pending
            if isinstance(record.extra, dict):
                candidate = record.extra.get("tool_call")
                if isinstance(candidate, dict):
                    approved_tool_call = dict(candidate)
                    siblings = record.extra.get("sibling_tool_calls")
                    if isinstance(siblings, list):
                        approved_tool_call["_sibling_tool_calls"] = siblings
                    remaining = record.extra.get("remaining_queue")
                    if isinstance(remaining, list):
                        approved_tool_call["_remaining_queue"] = remaining
                external_candidate = record.extra.get(
                    "external_agent_request",
                )
                if isinstance(external_candidate, dict):
                    approved_external_agent_request = dict(
                        external_candidate,
                    )
            return (
                None,
                True,
                approved_tool_call,
                approved_external_agent_request,
            )

        await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.DENIED,
        )
        return (
            Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=encode_runtime_i18n_text(
                            "acp.approval.chat.denied",
                            {
                                "toolName": pending.tool_name,
                            },
                        ),
                    ),
                ],
            ),
            True,
            None,
            None,
        )

    async def _queue_external_agent_preapproval(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        external_agent: ExternalAgentConfig,
        prompt_blocks: list[dict[str, str]],
        cwd: str,
        keep_session: bool,
        existing_session_id: str | None,
    ) -> Msg | None:
        """Pause dangerous ACP prompts until the user explicitly approves."""
        config = load_config()
        if not config.acp.require_approval:
            return None

        harness_cfg = config.acp.harnesses.get(external_agent.harness)
        if harness_cfg is None:
            return None
        if getattr(harness_cfg, "permission_broker_verified", False):
            return None
        if external_agent.preapproved:
            return None

        prompt_text = prompt_blocks_to_text(prompt_blocks)
        if not is_obviously_dangerous_prompt(prompt_text):
            return None

        from ..approvals import get_approval_service

        summary, result, waiting_text = build_prompt_approval_artifacts(
            harness=external_agent.harness,
            prompt_text=prompt_text,
            cwd=cwd,
        )
        await get_approval_service().create_pending(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            tool_name=f"ACP/{external_agent.harness}",
            result=result,
            extra={
                "approval_type": "acp_prompt",
                "approval_message": summary,
                "external_agent_request": {
                    "enabled": True,
                    "harness": external_agent.harness,
                    "keep_session": keep_session,
                    "cwd": cwd,
                    "existing_session_id": existing_session_id,
                    "prompt": prompt_text,
                    "keep_session_specified": True,
                    "preapproved": True,
                },
            },
        )
        return Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=waiting_text)],
        )

    async def query_handler(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Handle agent query.
        """
        logger.debug(
            f"AgentRunner.query_handler called: agent_id={self.agent_id}, "
            f"msgs={msgs}, request={request}",
        )
        query = _get_last_user_text(msgs)
        session_id = getattr(request, "session_id", "") or ""

        (
            approval_response,
            approval_consumed,
            approved_tool_call,
            approved_external_agent_request,
        ) = await self._resolve_pending_approval(session_id, query)
        if approval_response is not None:
            await self._append_external_agent_history(
                session_id=session_id,
                user_id=getattr(request, "user_id", "") or "",
                messages=[*list(msgs or []), approval_response],
            )
            yield approval_response, True
            user_id = getattr(request, "user_id", "") or ""
            await self._cleanup_denied_session_memory(
                session_id,
                user_id,
                denial_response=approval_response,
            )
            return

        if not approval_consumed and query and _is_command(query):
            logger.info("Command path: %s", query.strip()[:50])
            async for msg, last in run_command_path(request, msgs, self):
                yield msg, last
            return

        logger.debug(
            f"AgentRunner.stream_query: request={request}, "
            f"agent_id={self.agent_id}",
        )

        # Set agent context for model creation
        from ..agent_context import set_current_agent_id

        set_current_agent_id(self.agent_id)

        agent = None
        chat = None
        session_state_loaded = False
        try:
            session_id = request.session_id
            user_id = request.user_id
            channel = getattr(request, "channel", DEFAULT_CHANNEL)
            external_agent = merge_external_agent_configs(
                parse_external_agent_config(request),
                parse_external_agent_text(query),
            )
            if approved_external_agent_request:
                external_agent = ExternalAgentConfig(
                    **approved_external_agent_request,
                )

            logger.info(
                "Handle agent query:\n%s",
                json.dumps(
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "msgs_len": len(msgs) if msgs else 0,
                        "msgs_str": str(msgs)[:300] + "...",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            env_context = build_env_context(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                working_dir=(
                    str(self.workspace_dir)
                    if self.workspace_dir
                    else str(WORKING_DIR)
                ),
            )

            # Get MCP clients from manager (hot-reloadable)
            mcp_clients = []
            if self._mcp_manager is not None:
                mcp_clients = await self._mcp_manager.get_clients()

            name = "New Chat"
            if len(msgs) > 0:
                content = msgs[0].get_text_content()
                if content:
                    name = msgs[0].get_text_content()[:10]
                else:
                    name = "Media Message"

            logger.debug(
                f"DEBUG chat_manager status: "
                f"_chat_manager={self._chat_manager}, "
                f"is_none={self._chat_manager is None}, "
                f"agent_id={self.agent_id}",
            )

            if self._chat_manager is not None:
                logger.debug(
                    f"Runner: Calling get_or_create_chat for "
                    f"session_id={session_id}, user_id={user_id}, "
                    f"channel={channel}, name={name}",
                )
                chat = await self._chat_manager.get_or_create_chat(
                    session_id,
                    user_id,
                    channel,
                    name=name,
                )
                logger.debug(f"Runner: Got chat: {chat.id}")
            else:
                logger.warning(
                    f"ChatManager is None! Cannot auto-register chat for "
                    f"session_id={session_id}",
                )

            external_agent = self._restore_external_agent_from_chat_meta(
                external_agent,
                chat,
                query,
            )

            if external_agent is not None:
                chat_id = chat.id if chat is not None else session_id
                chat_meta = dict(getattr(chat, "meta", {}) or {})
                external_meta = dict(chat_meta.get("external_agent") or {})
                config = load_config()
                keep_session = self._resolve_external_agent_keep_session(
                    external_agent,
                    config.acp,
                )
                cwd = str(
                    external_agent.cwd
                    or external_meta.get("cwd")
                    or Path.cwd(),
                )
                existing_session_id = external_agent.existing_session_id
                if (
                    existing_session_id is None
                    and keep_session
                    and external_meta.get("acp_session_id")
                    and external_meta.get("harness") == external_agent.harness
                ):
                    existing_session_id = str(
                        external_meta.get("acp_session_id"),
                    )

                prompt_blocks = self._build_external_prompt_blocks(
                    msgs,
                    text_override=external_agent.prompt,
                )
                approval_message = (
                    await self._queue_external_agent_preapproval(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        external_agent=external_agent,
                        prompt_blocks=prompt_blocks,
                        cwd=cwd,
                        keep_session=keep_session,
                        existing_session_id=existing_session_id,
                    )
                )
                if approval_message is not None:
                    await self._append_external_agent_history(
                        session_id=session_id,
                        user_id=user_id,
                        messages=[*list(msgs or []), approval_message],
                    )
                    yield approval_message, True
                    return
                stream_queue: asyncio.Queue[tuple[Msg, bool]] = asyncio.Queue()
                persisted_messages = list(msgs or [])
                acp_service = self._get_acp_service()

                async def _push_message(message: Msg, last: bool) -> None:
                    persisted_messages.append(message)
                    await stream_queue.put((message, last))

                run_task = asyncio.create_task(
                    acp_service.run_turn(
                        chat_id=chat_id,
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        harness=external_agent.harness,
                        prompt_blocks=prompt_blocks,
                        cwd=cwd,
                        keep_session=keep_session,
                        preapproved=external_agent.preapproved,
                        existing_session_id=existing_session_id,
                        on_message=_push_message,
                    ),
                )

                try:
                    last_message_yielded = False
                    while True:
                        if run_task.done() and stream_queue.empty():
                            break
                        try:
                            message, last = await asyncio.wait_for(
                                stream_queue.get(),
                                timeout=0.1,
                            )
                        except asyncio.TimeoutError:
                            continue
                        last_message_yielded = last_message_yielded or last
                        yield message, last

                    drain_attempts = 0
                    while (
                        not last_message_yielded
                        and drain_attempts < ACP_DRAIN_MAX_ATTEMPTS
                    ):
                        try:
                            message, last = await asyncio.wait_for(
                                stream_queue.get(),
                                timeout=0.1,
                            )
                        except asyncio.TimeoutError:
                            drain_attempts += 1
                            if run_task.done():
                                continue
                            break
                        last_message_yielded = last_message_yielded or last
                        yield message, last

                    if not last_message_yielded and persisted_messages:
                        yield persisted_messages[-1], True

                    run_result = await run_task
                    await self._append_external_agent_history(
                        session_id=session_id,
                        user_id=user_id,
                        messages=persisted_messages,
                    )
                except ACPConfigurationError as exc:
                    err_msg = Msg(
                        name="Friday",
                        role="assistant",
                        content=[TextBlock(type="text", text=str(exc))],
                    )
                    persisted_messages.append(err_msg)
                    await self._append_external_agent_history(
                        session_id=session_id,
                        user_id=user_id,
                        messages=persisted_messages,
                    )
                    yield err_msg, True
                    return
                finally:
                    if not run_task.done():
                        run_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await run_task

                if chat is not None:
                    chat.meta = dict(chat.meta or {})
                    chat.meta["external_agent"] = {
                        "enabled": True,
                        "harness": external_agent.harness,
                        "keep_session": keep_session,
                        "acp_session_id": run_result.session_id,
                        "cwd": run_result.cwd,
                        "last_active_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(),
                        ),
                    }

                return

            # Load agent-specific configuration only for the normal agent path.
            agent_config = load_agent_config(self.agent_id)

            agent = CoPawAgent(
                agent_config=agent_config,
                env_context=env_context,
                mcp_clients=mcp_clients,
                memory_manager=self.memory_manager,
                request_context={
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                    "agent_id": self.agent_id,
                    **(
                        {
                            "forced_tool_call_json": json.dumps(
                                approved_tool_call,
                                ensure_ascii=False,
                            ),
                        }
                        if approved_tool_call
                        else {}
                    ),
                },
                workspace_dir=self.workspace_dir,
                task_tracker=self._task_tracker,
            )
            await agent.register_mcp_clients()
            agent.set_console_output_enabled(enabled=False)

            logger.debug(
                f"Agent Query msgs {msgs}",
            )

            try:
                await self.session.load_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    agent=agent,
                )
            except KeyError as e:
                logger.warning(
                    "load_session_state skipped (state schema mismatch): %s; "
                    "will save fresh state on completion to recover file",
                    e,
                )
            session_state_loaded = True

            # Rebuild system prompt so it always reflects the latest
            # AGENTS.md / SOUL.md / PROFILE.md, not the stale one saved
            # in the session state.
            agent.rebuild_sys_prompt()

            async for msg, last in stream_printing_messages(
                agents=[agent],
                coroutine_task=agent(msgs),
            ):
                yield msg, last

        except asyncio.CancelledError as exc:
            logger.info(f"query_handler: {session_id} cancelled!")
            if agent is not None:
                await agent.interrupt()
            raise AgentException("Task has been cancelled!") from exc
        except Exception as e:
            debug_dump_path = write_query_error_dump(
                request=request,
                exc=e,
                locals_=locals(),
            )
            path_hint = (
                f"\n(Details:  {debug_dump_path})" if debug_dump_path else ""
            )
            logger.exception(f"Error in query handler: {e}{path_hint}")
            if debug_dump_path:
                setattr(e, "debug_dump_path", debug_dump_path)
                if hasattr(e, "add_note"):
                    e.add_note(
                        f"(Details:  {debug_dump_path})",
                    )
                suffix = f"\n(Details:  {debug_dump_path})"
                e.args = (
                    (f"{e.args[0]}{suffix}" if e.args else suffix.strip()),
                ) + e.args[1:]
            raise
        finally:
            if agent is not None and session_state_loaded:
                await self.session.save_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    agent=agent,
                )

            if self._chat_manager is not None and chat is not None:
                await self._chat_manager.update_chat(chat)

    async def _cleanup_denied_session_memory(
        self,
        session_id: str,
        user_id: str,
        denial_response: "Msg | None" = None,
    ) -> None:
        """Clean up session memory after a tool-guard denial.

        In the deny path (no agent is created), this method:

        1. Removes the LLM denial explanation (the assistant message
           immediately following the last marked entry).
        2. Strips ``TOOL_GUARD_DENIED_MARK`` from all marks lists so
           the kept tool-call info becomes normal memory entries.
        3. Appends *denial_response* (e.g. "❌ Tool denied") to the
           persisted session memory.
        """
        if not hasattr(self, "session") or self.session is None:
            return

        path = self.session._get_save_path(  # pylint: disable=protected-access
            session_id,
            user_id,
        )
        if not Path(path).exists():
            return

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as f:
                states = json.load(f)

            agent_state = states.get("agent", {})
            memory_state = agent_state.get("memory", {})
            content = memory_state.get("content", [])

            if not content:
                return

            def _is_marked(entry):
                return (
                    isinstance(entry, list)
                    and len(entry) >= 2
                    and isinstance(entry[1], list)
                    and TOOL_GUARD_DENIED_MARK in entry[1]
                )

            last_marked_idx = -1
            for i, entry in enumerate(content):
                if _is_marked(entry):
                    last_marked_idx = i

            modified = False

            if last_marked_idx >= 0 and last_marked_idx + 1 < len(content):
                next_entry = content[last_marked_idx + 1]
                if (
                    isinstance(next_entry, list)
                    and len(next_entry) >= 1
                    and isinstance(next_entry[0], dict)
                    and next_entry[0].get("role") == "assistant"
                ):
                    del content[last_marked_idx + 1]
                    modified = True

            for entry in content:
                if _is_marked(entry):
                    entry[1].remove(TOOL_GUARD_DENIED_MARK)
                    modified = True

            if denial_response is not None:
                ts = getattr(denial_response, "timestamp", None)
                msg_dict = {
                    "id": getattr(denial_response, "id", ""),
                    "name": getattr(denial_response, "name", "Friday"),
                    "role": getattr(denial_response, "role", "assistant"),
                    "content": denial_response.content,
                    "metadata": getattr(
                        denial_response,
                        "metadata",
                        None,
                    ),
                    "timestamp": str(ts) if ts is not None else "",
                }
                content.append([msg_dict, []])
                modified = True

            if modified:
                with open(
                    path,
                    "w",
                    encoding="utf-8",
                    errors="surrogatepass",
                ) as f:
                    json.dump(states, f, ensure_ascii=False)
                logger.info(
                    "Tool guard: cleaned up denied session memory in %s",
                    path,
                )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to clean up denied messages from session %s",
                session_id,
                exc_info=True,
            )

    async def init_handler(self, *args, **kwargs):
        """
        Init handler.
        """
        # Load environment variables from .env file
        # env_path = Path(__file__).resolve().parents[4] / ".env"
        env_path = Path("./") / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
        else:
            logger.debug(
                f".env file not found at {env_path}, "
                "using existing environment variables",
            )

        session_dir = str(
            (self.workspace_dir if self.workspace_dir else WORKING_DIR)
            / "sessions",
        )
        self.session = SafeJSONSession(save_dir=session_dir)

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
