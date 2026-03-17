# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
    ModelContextLengthExceededException,
    ModelExecutionException,
    ModelNotFoundException,
    ModelQuotaExceededException,
    ModelTimeoutException,
    NetworkException,
    UnauthorizedModelAccessException,
    UnknownAgentException,
)
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
from ...config.config import load_agent_config, AgentsRunningConfig
from ...constant import (
    TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    WORKING_DIR,
)
from ...security.tool_guard.approval import ApprovalDecision

logger = logging.getLogger(__name__)


class _Rule:
    """Declarative rule for mapping raw exceptions to error codes."""

    __slots__ = (
        "factory",
        "status_codes",
        "type_keywords",
        "msg_keywords",
        "base_types",
    )

    def __init__(
        self,
        factory,
        *,
        status_codes: tuple[int, ...] = (),
        type_keywords: tuple[str, ...] = (),
        msg_keywords: tuple[str, ...] = (),
        base_types: tuple[type, ...] = (),
    ):
        self.factory = factory
        self.status_codes = status_codes
        self.type_keywords = type_keywords
        self.msg_keywords = msg_keywords
        self.base_types = base_types

    def matches(self, exc, exc_type, exc_msg, status) -> bool:
        if self.base_types and isinstance(exc, self.base_types):
            return True
        if self.status_codes and status in self.status_codes:
            return True
        if self.type_keywords and any(
            k in exc_type for k in self.type_keywords
        ):
            return True
        if self.msg_keywords and any(k in exc_msg for k in self.msg_keywords):
            return True
        return False


def _make_auth(details):
    return UnauthorizedModelAccessException(model_name="", details=details)


def _make_quota(details):
    return ModelQuotaExceededException(model_name="", details=details)


def _make_context(details):
    return ModelContextLengthExceededException(model_name="", details=details)


def _make_timeout(details):
    return ModelTimeoutException(model_name="", timeout=0, details=details)


def _make_network(details):
    return NetworkException(
        message=details["original_message"],
        details=details,
    )


def _make_exec(details):
    return ModelExecutionException(model_name="", details=details)


def _make_not_found(details):
    return ModelNotFoundException(model_name="", details=details)


_RULES: list[_Rule] = [
    _Rule(
        _make_auth,
        status_codes=(401,),
        type_keywords=("AuthenticationError",),
        msg_keywords=(
            "api_key",
            "api key",
            "unauthorized",
            "invalid x-api-key",
        ),
    ),
    _Rule(
        _make_quota,
        status_codes=(429,),
        type_keywords=("RateLimitError", "OverloadedError"),
        msg_keywords=("rate_limit", "rate limit", "quota"),
    ),
    _Rule(
        _make_context,
        status_codes=(413,),
        type_keywords=("LengthFinishReasonError", "RequestTooLargeError"),
        msg_keywords=(
            "context_length",
            "maximum context length",
            "too many tokens",
        ),
    ),
    _Rule(
        _make_timeout,
        status_codes=(504,),
        type_keywords=("Timeout", "DeadlineExceeded"),
        base_types=(TimeoutError,),
    ),
    _Rule(
        _make_network,
        status_codes=(503,),
        type_keywords=("ConnectionError", "ConnectError"),
        base_types=(ConnectionError,),
    ),
    _Rule(
        _make_exec,
        type_keywords=("ContentFilterFinishReasonError",),
        msg_keywords=("content_filter", "content management policy"),
    ),
    _Rule(
        _make_not_found,
        status_codes=(404,),
        type_keywords=("NotFoundError",),
        msg_keywords=("model not found", "does not exist"),
    ),
    _Rule(
        _make_exec,
        status_codes=(400,),
        type_keywords=("BadRequestError",),
    ),
]


def _classify_exception(exc: Exception) -> AppBaseException:
    """Map a raw exception to an ``AppBaseException`` with a specific error
    code so that agentscope-runtime can propagate a meaningful code instead
    of the catch-all ``AGENT_UNKNOWN_ERROR``.

    The matching is intentionally based on *features* (type name strings,
    ``status_code`` attribute, message keywords) rather than ``isinstance``
    checks against concrete SDK classes, so it works across providers
    (OpenAI, Anthropic, Google Gemini, httpx, …) without importing them.
    """
    if isinstance(exc, AppBaseException):
        return exc

    exc_type = type(exc).__name__
    exc_msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(
        exc,
        "status",
        None,
    )
    details = {"original_type": exc_type, "original_message": str(exc)}

    for rule in _RULES:
        if rule.matches(exc, exc_type, exc_msg, status):
            return rule.factory(details)

    # Generic server errors (5xx) not covered by specific rules
    if isinstance(status, int) and 500 <= status < 600:
        return _make_exec(details)

    # Provider / model not configured (ValueError from provider_manager)
    if isinstance(exc, (ValueError, NotImplementedError)) and (
        "not found" in exc_msg
        or "not configured" in exc_msg
        or "no active model" in exc_msg
    ):
        return _make_not_found(details)

    return UnknownAgentException(original_exception=exc, details=details)


class AgentRunner(Runner):
    def __init__(
        self,
        agent_id: str = "default",
        workspace_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self.agent_id = agent_id  # Store agent_id for config loading
        self.workspace_dir = (
            workspace_dir  # Store workspace_dir for prompt building
        )
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self.memory_manager: MemoryManager | None = None

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
        logger.debug(
            f"AgentRunner.query_handler called: agent_id={self.agent_id}, "
            f"msgs={msgs}, request={request}",
        )
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

            # Load agent-specific configuration
            agent_config = load_agent_config(self.agent_id)

            # Get running config with defaults
            running_config = agent_config.running
            if running_config is None:
                running_config = AgentsRunningConfig()

            max_iters = running_config.max_iters
            max_input_length = running_config.max_input_length
            language = agent_config.language

            agent = CoPawAgent(
                env_context=env_context,
                mcp_clients=mcp_clients,
                memory_manager=self.memory_manager,
                request_context={
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                    "agent_id": self.agent_id,
                },
                max_iters=max_iters,
                max_input_length=max_input_length,
                memory_compact_threshold=(
                    running_config.memory_compact_threshold
                ),
                memory_compact_reserve=running_config.memory_compact_reserve,
                enable_tool_result_compact=(
                    running_config.enable_tool_result_compact
                ),
                tool_result_compact_keep_n=(
                    running_config.tool_result_compact_keep_n
                ),
                language=language,
                workspace_dir=self.workspace_dir,
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

            classified = _classify_exception(e)
            if debug_dump_path:
                setattr(classified, "debug_dump_path", debug_dump_path)
                if hasattr(classified, "add_note"):
                    classified.add_note(
                        f"(Details:  {debug_dump_path})",
                    )
                classified.details["debug_dump_path"] = debug_dump_path
            raise classified from e
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

        session_dir = str(
            (self.workspace_dir if self.workspace_dir else WORKING_DIR)
            / "sessions",
        )
        self.session = SafeJSONSession(save_dir=session_dir)

        # Only create and start MemoryManager if not already set by Workspace
        try:
            if self.memory_manager is None:
                self.memory_manager = MemoryManager(
                    working_dir=(
                        str(self.workspace_dir)
                        if self.workspace_dir
                        else str(WORKING_DIR)
                    ),
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
