# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from pathlib import Path

from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
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
from ...agents.memory import MemoryManager
from ...agents.react_agent import CoPawAgent
from ...security.tool_guard.models import TOOL_GUARD_DENIED_MARK
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
    merge_external_agent_configs,
    parse_external_agent_config,
    parse_external_agent_text,
)

logger = logging.getLogger(__name__)


class AgentRunner(Runner):
    def __init__(self) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self.memory_manager: MemoryManager | None = None
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

    def _get_acp_service(self) -> ACPService:
        """Return the lazily-created ACP service instance."""
        config = load_config()
        if self._acp_service is None or self._acp_service.config != config.acp:
            self._acp_service = ACPService(config=config.acp)
        return self._acp_service

    def _build_external_prompt_blocks(
        self,
        msgs,
        text_override: str | None = None,
    ) -> list[dict]:
        """Convert the last user message into ACP prompt blocks."""
        if text_override is not None:
            return [{"type": "text", "text": text_override}]

        if not msgs:
            return [{"type": "text", "text": ""}]

        last = msgs[-1]
        content = getattr(last, "content", None)
        if not content and isinstance(last, dict):
            content = last.get("content")

        blocks: list[dict] = []
        for block in content or []:
            block_type = getattr(block, "type", None)
            if block_type is None and isinstance(block, dict):
                block_type = block.get("type")

            if block_type == "text":
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")
                if text:
                    blocks.append({"type": "text", "text": str(text)})

        if blocks:
            return blocks

        query = _get_last_user_text(msgs) or ""
        return [{"type": "text", "text": query}]

    async def _append_external_agent_history(
        self,
        *,
        session_id: str,
        user_id: str,
        messages: list[Msg],
    ) -> None:
        """Persist ACP turns without touching the normal agent state schema."""
        if not session_id or self.session is None or not messages:
            return

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

        await memory.add(messages)
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
    ) -> tuple[Msg | None, bool]:
        """Check for a pending tool-guard approval for *session_id*.

        Returns ``(response_msg, was_consumed)``:

        - ``(None, False)`` — no pending approval, continue normally.
        - ``(Msg, True)``   — denied; yield the Msg and stop.
        - ``(None, True)``  — approved; skip the command path and let
          the message reach the agent so the LLM can re-call the tool.
        """
        if not session_id:
            return None, False

        from ..approvals import get_approval_service

        svc = get_approval_service()
        pending = await svc.get_pending_by_session(session_id)
        if pending is None:
            return None, False

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
                            text=(
                                f"⏰ Tool `{pending.tool_name}` approval "
                                f"timed out ({int(elapsed)}s) — denied.\n"
                                f"工具 `{pending.tool_name}` 审批超时"
                                f"（{int(elapsed)}s），已拒绝执行。"
                            ),
                        ),
                    ],
                ),
                True,
            )

        normalized = (query or "").strip().lower()
        if normalized in ("/daemon approve", "/approve"):
            await svc.resolve_request(
                pending.request_id,
                ApprovalDecision.APPROVED,
            )
            return None, True

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
                        text=(
                            f"❌ Tool `{pending.tool_name}` denied.\n"
                            f"工具 `{pending.tool_name}` 已拒绝执行。"
                        ),
                    ),
                ],
            ),
            True,
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
        query = _get_last_user_text(msgs)
        session_id = getattr(request, "session_id", "") or ""

        (
            approval_response,
            approval_consumed,
        ) = await self._resolve_pending_approval(session_id, query)
        if approval_response is not None:
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
                working_dir=str(WORKING_DIR),
            )

            # Get MCP clients from manager (hot-reloadable)
            mcp_clients = []
            if self._mcp_manager is not None:
                mcp_clients = await self._mcp_manager.get_clients()

            config = load_config()
            max_iters = config.agents.running.max_iters
            max_input_length = config.agents.running.max_input_length

            agent = CoPawAgent(
                env_context=env_context,
                mcp_clients=mcp_clients,
                memory_manager=self.memory_manager,
                request_context={
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                },
                max_iters=max_iters,
                max_input_length=max_input_length,
            )
            await agent.register_mcp_clients()
            agent.set_console_output_enabled(enabled=False)

            logger.debug(
                f"Agent Query msgs {msgs}",
            )

            name = "New Chat"
            if len(msgs) > 0:
                content = msgs[0].get_text_content()
                if content:
                    name = msgs[0].get_text_content()[:10]
                else:
                    name = "Media Message"

            if self._chat_manager is not None:
                chat = await self._chat_manager.get_or_create_chat(
                    session_id,
                    user_id,
                    channel,
                    name=name,
                )

            if external_agent is not None:
                chat_id = chat.id if chat is not None else session_id
                chat_meta = dict(getattr(chat, "meta", {}) or {})
                external_meta = dict(chat_meta.get("external_agent") or {})
                default_cwd = str(Path.cwd())
                cwd = str(
                    external_agent.cwd
                    or
                    external_meta.get("cwd")
                    or default_cwd
                )
                existing_session_id = external_agent.existing_session_id
                
                # Only reuse session if harness matches
                if (
                    existing_session_id is None
                    and external_agent.keep_session
                    and external_meta.get("acp_session_id")
                    and external_meta.get("harness") == external_agent.harness
                ):
                    existing_session_id = str(external_meta.get("acp_session_id"))
                prompt_blocks = self._build_external_prompt_blocks(
                    msgs,
                    text_override=external_agent.prompt,
                )
                stream_queue: asyncio.Queue[tuple[Msg, bool]] = asyncio.Queue()
                persisted_messages = list(msgs or [])
                acp_service = self._get_acp_service()

                async def _push_message(message: Msg, last: bool) -> None:
                    # Persist all messages but deduplicate by ID to avoid duplicate streaming chunks
                    msg_id = getattr(message, 'id', None)
                    if msg_id:
                        # Remove any existing message with same ID (keeps only latest version)
                        persisted_messages[:] = [
                            m for m in persisted_messages 
                            if getattr(m, 'id', None) != msg_id
                        ]
                    persisted_messages.append(message)
                    # Use INFO level for critical ACP flow tracking
                    log_fn = logger.info if last else logger.debug
                    log_fn(
                        "ACP message pushed: id=%s last=%s role=%s content_len=%d persisted_count=%d",
                        msg_id,
                        last,
                        getattr(message, 'role', '?'),
                        len(str(getattr(message, 'content', ''))),
                        len(persisted_messages),
                    )
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
                        keep_session=external_agent.keep_session,
                        existing_session_id=existing_session_id,
                        on_message=_push_message,
                    ),
                )

                try:
                    last_message_yielded = False
                    message_count = 0
                    while True:
                        if run_task.done() and stream_queue.empty():
                            logger.info("ACP stream loop: run_task done and queue empty, breaking")
                            break
                        try:
                            message, last = await asyncio.wait_for(
                                stream_queue.get(),
                                timeout=0.1,
                            )
                            message_count += 1
                            msg_id = getattr(message, 'id', '?')
                            msg_preview = str(message.content)[:50] if message.content else 'None'
                            log_fn = logger.info if last else logger.debug
                            log_fn("ACP stream yield #%d: id=%s last=%s content=%s...", 
                                        message_count, msg_id, last, msg_preview)
                        except asyncio.TimeoutError:
                            continue
                        if last:
                            last_message_yielded = True
                            logger.info("ACP stream: last=True message yielded (count=%d)", message_count)
                        yield message, last

                    # Drain any remaining messages to ensure we don't miss the last=True message
                    # This handles race conditions where finalize() is called after run_task.done()
                    drain_attempts = 0
                    max_drain_attempts = ACP_DRAIN_MAX_ATTEMPTS
                    logger.debug("ACP stream: starting drain loop, last_message_yielded=%s", last_message_yielded)
                    while not last_message_yielded and drain_attempts < max_drain_attempts:
                        try:
                            message, last = await asyncio.wait_for(
                                stream_queue.get(),
                                timeout=0.1,
                            )
                            message_count += 1
                            msg_id = getattr(message, 'id', '?')
                            msg_preview = str(message.content)[:50] if message.content else 'None'
                            logger.debug("ACP stream drain #%d: id=%s last=%s content=%s...", 
                                        message_count, msg_id, last, msg_preview)
                            if last:
                                last_message_yielded = True
                                logger.debug("ACP stream: last=True message yielded in drain (count=%d)", message_count)
                            yield message, last
                        except asyncio.TimeoutError:
                            drain_attempts += 1
                            if run_task.done():
                                continue
                            break
                    logger.debug("ACP stream: drain loop ended, attempts=%d, last_message_yielded=%s", 
                                drain_attempts, last_message_yielded)

                    # Ensure we always yield a final message with last=True if not already done
                    if not last_message_yielded and persisted_messages:
                        final_msg = persisted_messages[-1]
                        final_msg_id = getattr(final_msg, 'id', '?')
                        final_preview = str(final_msg.content)[:50] if final_msg.content else 'None'
                        logger.debug(
                            "ACP yielding final last=True message from persisted: id=%s, content=%s...",
                            final_msg_id, final_preview
                        )
                        yield final_msg, True
                    else:
                        logger.debug("ACP stream: skip fallback yield - last_message_yielded=%s, persisted_count=%d",
                                    last_message_yielded, len(persisted_messages))

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
                        "keep_session": external_agent.keep_session,
                        "acp_session_id": run_result.session_id,
                        "cwd": run_result.cwd,
                        "last_active_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }

                return

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
            raise RuntimeError("Task has been cancelled!") from exc
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
        env_path = Path(__file__).resolve().parents[4] / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
        else:
            logger.debug(
                f".env file not found at {env_path}, "
                "using existing environment variables",
            )

        session_dir = str(WORKING_DIR / "sessions")
        self.session = SafeJSONSession(save_dir=session_dir)

        try:
            if self.memory_manager is None:
                self.memory_manager = MemoryManager(
                    working_dir=str(WORKING_DIR),
                )
            await self.memory_manager.start()
        except Exception as e:
            logger.exception(f"MemoryManager start failed: {e}")

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
        try:
            if self.memory_manager is not None:
                await self.memory_manager.close()
        except Exception as e:
            logger.warning(f"MemoryManager stop failed: {e}")
