# -*- coding: utf-8 -*-
"""CoPaw Agent - Main agent implementation.

This module provides the main CoPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.
"""
import asyncio
import logging
import os
from typing import Any, List, Literal, Optional, Type

from agentscope.agent import ReActAgent
from agentscope.mcp import HttpStatefulClient, StdIOStatefulClient
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg
from agentscope.tool import Toolkit
from anyio import ClosedResourceError
from pydantic import BaseModel

from .command_handler import CommandHandler
from .hooks import BootstrapHook, MemoryCompactionHook
from .model_factory import create_model_and_formatter
from .prompt import build_system_prompt_from_working_dir
from .skills_manager import (
    ensure_skills_initialized,
    get_working_skills_dir,
    list_available_skills,
)
from .tools import (
    browser_use,
    desktop_screenshot,
    edit_file,
    execute_shell_command,
    get_current_time,
    get_token_usage,
    read_file,
    send_file_to_user,
    write_file,
    create_memory_search_tool,
)
from .utils import process_file_and_media_blocks_in_message
from ..agents.memory import MemoryManager
from ..config import load_config
from ..constant import (
    MEMORY_COMPACT_RATIO,
    WORKING_DIR,
)
from ..security.tool_guard.models import TOOL_GUARD_DENIED_MARK

logger = logging.getLogger(__name__)

# Valid namesake strategies for tool registration
NamesakeStrategy = Literal["override", "skip", "raise", "rename"]


def normalize_reasoning_tool_choice(
    tool_choice: Literal["auto", "none", "required"] | None,
    has_tools: bool,
) -> Literal["auto", "none", "required"] | None:
    """Normalize tool_choice for reasoning to reduce provider variance."""
    if tool_choice is None and has_tools:
        return "auto"
    return tool_choice


class CoPawAgent(ReActAgent):
    """CoPaw Agent with integrated tools, skills, and memory management.

    This agent extends ReActAgent with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - System command handling (/compact, /new, etc.)
    """

    def __init__(
        self,
        env_context: Optional[str] = None,
        enable_memory_manager: bool = True,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: MemoryManager | None = None,
        request_context: Optional[dict[str, str]] = None,
        max_iters: int = 50,
        max_input_length: int = 128 * 1024,  # 128K = 131072 tokens
        namesake_strategy: NamesakeStrategy = "skip",
    ):
        """Initialize CoPawAgent.

        Args:
            env_context: Optional environment context to prepend to
                system prompt
            enable_memory_manager: Whether to enable memory manager
            mcp_clients: Optional list of MCP clients for tool
                integration
            memory_manager: Optional memory manager instance
            max_iters: Maximum number of reasoning-acting iterations
                (default: 50)
            max_input_length: Maximum input length in tokens for model
                context window (default: 128K = 131072)
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")
        """
        self._env_context = env_context
        self._request_context = dict(request_context or {})
        self._max_input_length = max_input_length
        self._mcp_clients = mcp_clients or []
        self._namesake_strategy = namesake_strategy

        # Memory compaction threshold: configurable ratio of max_input_length
        self._memory_compact_threshold = int(
            max_input_length * MEMORY_COMPACT_RATIO,
        )

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit(namesake_strategy=namesake_strategy)

        # Load and register skills
        self._register_skills(toolkit)

        # Build system prompt
        sys_prompt = self._build_sys_prompt()

        # Create model and formatter using factory method
        model, formatter = create_model_and_formatter()

        # Initialize parent ReActAgent
        super().__init__(
            name="Friday",
            model=model,
            sys_prompt=sys_prompt,
            toolkit=toolkit,
            memory=InMemoryMemory(),
            formatter=formatter,
            max_iters=max_iters,
        )

        # Setup memory manager
        self._setup_memory_manager(
            enable_memory_manager,
            memory_manager,
            namesake_strategy,
        )

        # Setup command handler
        self.command_handler = CommandHandler(
            agent_name=self.name,
            memory=self.memory,
            memory_manager=self.memory_manager,
            enable_memory_manager=self._enable_memory_manager,
        )

        # Register hooks
        self._register_hooks()

    def _create_toolkit(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> Toolkit:
        """Create and populate toolkit with built-in tools.

        Args:
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")

        Returns:
            Configured toolkit instance
        """
        toolkit = Toolkit()

        # Load config to check which tools are enabled
        config = load_config()
        enabled_tools = {}
        if hasattr(config, "tools") and hasattr(config.tools, "builtin_tools"):
            enabled_tools = {
                name: tool_config.enabled
                for name, tool_config in config.tools.builtin_tools.items()
            }

        # Map of tool functions
        tool_functions = {
            "execute_shell_command": execute_shell_command,
            "read_file": read_file,
            "write_file": write_file,
            "edit_file": edit_file,
            "browser_use": browser_use,
            "desktop_screenshot": desktop_screenshot,
            "send_file_to_user": send_file_to_user,
            "get_current_time": get_current_time,
            "get_token_usage": get_token_usage,
        }

        # Register only enabled tools
        for tool_name, tool_func in tool_functions.items():
            # If tool not in config, enable by default (backward compatibility)
            if enabled_tools.get(tool_name, True):
                toolkit.register_tool_function(
                    tool_func,
                    namesake_strategy=namesake_strategy,
                )
                logger.debug("Registered tool: %s", tool_name)
            else:
                logger.debug("Skipped disabled tool: %s", tool_name)

        return toolkit

    def _register_skills(self, toolkit: Toolkit) -> None:
        """Load and register skills from working directory.

        Args:
            toolkit: Toolkit to register skills to
        """
        # Check skills initialization
        ensure_skills_initialized()

        working_skills_dir = get_working_skills_dir()
        available_skills = list_available_skills()

        for skill_name in available_skills:
            skill_dir = working_skills_dir / skill_name
            if skill_dir.exists():
                try:
                    toolkit.register_agent_skill(str(skill_dir))
                    logger.debug("Registered skill: %s", skill_name)
                except Exception as e:
                    logger.error(
                        "Failed to register skill '%s': %s",
                        skill_name,
                        e,
                    )

    def _build_sys_prompt(self) -> str:
        """Build system prompt from working dir files and env context.

        Returns:
            Complete system prompt string
        """
        sys_prompt = build_system_prompt_from_working_dir()
        if self._env_context is not None:
            sys_prompt = self._env_context + "\n\n" + sys_prompt
        return sys_prompt

    def _setup_memory_manager(
        self,
        enable_memory_manager: bool,
        memory_manager: MemoryManager | None,
        namesake_strategy: NamesakeStrategy,
    ) -> None:
        """Setup memory manager and register memory search tool if enabled.

        Args:
            enable_memory_manager: Whether to enable memory manager
            memory_manager: Optional memory manager instance
            namesake_strategy: Strategy to handle namesake tool functions
        """
        # Check env var: if ENABLE_MEMORY_MANAGER=false, disable memory manager
        env_enable_mm = os.getenv("ENABLE_MEMORY_MANAGER", "")
        if env_enable_mm.lower() == "false":
            enable_memory_manager = False

        self._enable_memory_manager: bool = enable_memory_manager
        self.memory_manager = memory_manager

        # Register memory_search tool if enabled and available
        if self._enable_memory_manager and self.memory_manager is not None:
            # update memory manager
            self.memory = self.memory_manager.get_in_memory_memory()
            self.memory_manager.chat_model = self.model
            self.memory_manager.formatter = self.formatter

            # Register memory_search as a tool function
            self.toolkit.register_tool_function(
                create_memory_search_tool(self.memory_manager),
                namesake_strategy=namesake_strategy,
            )
            logger.debug("Registered memory_search tool")

    def _register_hooks(self) -> None:
        """Register pre-reasoning and pre-acting hooks."""
        # Bootstrap hook - checks BOOTSTRAP.md on first interaction
        config = load_config()
        bootstrap_hook = BootstrapHook(
            working_dir=WORKING_DIR,
            language=config.agents.language,
        )
        self.register_instance_hook(
            hook_type="pre_reasoning",
            hook_name="bootstrap_hook",
            hook=bootstrap_hook.__call__,
        )
        logger.debug("Registered bootstrap hook")

        # Memory compaction hook - auto-compact when context is full
        if self._enable_memory_manager and self.memory_manager is not None:
            memory_compact_hook = MemoryCompactionHook(
                memory_manager=self.memory_manager,
            )
            self.register_instance_hook(
                hook_type="pre_reasoning",
                hook_name="memory_compact_hook",
                hook=memory_compact_hook.__call__,
            )
            logger.debug("Registered memory compaction hook")

    def rebuild_sys_prompt(self) -> None:
        """Rebuild and replace the system prompt.

        Useful after load_session_state to ensure the prompt reflects
        the latest AGENTS.md / SOUL.md / PROFILE.md on disk.

        Updates both self._sys_prompt and the first system-role
        message stored in self.memory.content (if one exists).
        """
        self._sys_prompt = self._build_sys_prompt()

        for msg, _marks in self.memory.content:
            if msg.role == "system":
                msg.content = self.sys_prompt
            break

    async def register_mcp_clients(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register MCP clients on this agent's toolkit after construction.

        Args:
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")
        """
        for i, client in enumerate(self._mcp_clients):
            client_name = getattr(client, "name", repr(client))
            try:
                await self.toolkit.register_mcp_client(
                    client,
                    namesake_strategy=namesake_strategy,
                )
            except (ClosedResourceError, asyncio.CancelledError) as error:
                if self._should_propagate_cancelled_error(error):
                    raise
                logger.warning(
                    "MCP client '%s' session interrupted while listing tools; "
                    "trying recovery",
                    client_name,
                )
                recovered_client = await self._recover_mcp_client(client)
                if recovered_client is not None:
                    self._mcp_clients[i] = recovered_client
                    try:
                        await self.toolkit.register_mcp_client(
                            recovered_client,
                            namesake_strategy=namesake_strategy,
                        )
                        continue
                    except asyncio.CancelledError as recover_error:
                        if self._should_propagate_cancelled_error(
                            recover_error,
                        ):
                            raise
                        logger.warning(
                            "MCP client '%s' registration cancelled after "
                            "recovery, skipping",
                            client_name,
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "MCP client '%s' still unavailable after "
                            "recovery, skipping: %s",
                            client_name,
                            e,
                        )
                else:
                    logger.warning(
                        "MCP client '%s' recovery failed, skipping",
                        client_name,
                    )
            except Exception as e:  # pylint: disable=broad-except
                logger.exception(
                    "Unexpected error registering MCP client '%s': %s",
                    client_name,
                    e,
                )
                raise

    async def _recover_mcp_client(self, client: Any) -> Any | None:
        """Recover MCP client from broken session and return healthy client."""
        if await self._reconnect_mcp_client(client):
            return client

        rebuilt_client = self._rebuild_mcp_client(client)
        if rebuilt_client is None:
            return None

        if await self._reconnect_mcp_client(rebuilt_client):
            return self._reuse_shared_client_reference(
                original_client=client,
                rebuilt_client=rebuilt_client,
            )

        return None

    @staticmethod
    def _reuse_shared_client_reference(
        original_client: Any,
        rebuilt_client: Any,
    ) -> Any:
        """Keep manager-shared client reference stable after rebuild."""
        original_dict = getattr(original_client, "__dict__", None)
        rebuilt_dict = getattr(rebuilt_client, "__dict__", None)
        if isinstance(original_dict, dict) and isinstance(rebuilt_dict, dict):
            original_dict.update(rebuilt_dict)
            return original_client
        return rebuilt_client

    @staticmethod
    def _should_propagate_cancelled_error(error: BaseException) -> bool:
        """Only swallow MCP-internal cancellations, not task cancellation."""
        if not isinstance(error, asyncio.CancelledError):
            return False

        task = asyncio.current_task()
        if task is None:
            return False

        cancelling = getattr(task, "cancelling", None)
        if callable(cancelling):
            return cancelling() > 0

        # Python < 3.11: Task.cancelling() is unavailable.
        # Fall back to propagating CancelledError to avoid swallowing
        # genuine task cancellations when we cannot inspect the state.
        return True

    @staticmethod
    async def _reconnect_mcp_client(
        client: Any,
        timeout: float = 60.0,
    ) -> bool:
        """Best-effort reconnect for stateful MCP clients."""
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            try:
                await close_fn()
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception:  # pylint: disable=broad-except
                pass

        connect_fn = getattr(client, "connect", None)
        if not callable(connect_fn):
            return False

        try:
            await asyncio.wait_for(connect_fn(), timeout=timeout)
            return True
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except asyncio.TimeoutError:
            return False
        except Exception:  # pylint: disable=broad-except
            return False

    @staticmethod
    def _rebuild_mcp_client(client: Any) -> Any | None:
        """Rebuild a fresh MCP client instance from stored config metadata."""
        rebuild_info = getattr(client, "_copaw_rebuild_info", None)
        if not isinstance(rebuild_info, dict):
            return None

        transport = rebuild_info.get("transport")
        name = rebuild_info.get("name")

        try:
            if transport == "stdio":
                rebuilt_client = StdIOStatefulClient(
                    name=name,
                    command=rebuild_info.get("command"),
                    args=rebuild_info.get("args", []),
                    env=rebuild_info.get("env", {}),
                    cwd=rebuild_info.get("cwd"),
                )
                setattr(rebuilt_client, "_copaw_rebuild_info", rebuild_info)
                return rebuilt_client

            rebuilt_client = HttpStatefulClient(
                name=name,
                transport=transport,
                url=rebuild_info.get("url"),
                headers=rebuild_info.get("headers"),
            )
            setattr(rebuilt_client, "_copaw_rebuild_info", rebuild_info)
            return rebuilt_client
        except Exception:  # pylint: disable=broad-except
            return None

    # ------------------------------------------------------------------
    # Tool-guard: override _acting to check before execution
    # ------------------------------------------------------------------

    def _init_tool_guard(self) -> None:
        """Lazy-init tool-guard components (called once on first _acting)."""
        from copaw.security.tool_guard.engine import get_guard_engine
        from copaw.security.tool_guard.utils import (
            resolve_guarded_tools,
            resolve_denied_tools,
        )
        from copaw.app.approvals import get_approval_service

        self._tool_guard_engine = get_guard_engine()
        self._tool_guard_guarded_tools = resolve_guarded_tools()
        self._tool_guard_denied_tools: set[str] = resolve_denied_tools()
        self._tool_guard_approval_service = get_approval_service()
        self._tool_guard_pending_info: dict | None = None

    def _should_guard_tool(self, tool_name: str) -> bool:
        """Check if *tool_name* is in the guarded scope."""
        if self._tool_guard_guarded_tools is None:
            return True  # None means guard ALL tools
        return tool_name in self._tool_guard_guarded_tools

    def _should_require_approval(self) -> bool:
        """True when the current session can use the /daemon approve flow.

        Approval is requested as long as a ``session_id`` is available
        so the runner can match the subsequent ``/daemon approve``
        message to the correct pending record.
        """
        return bool(self._request_context.get("session_id"))

    async def _acting(self, tool_call) -> dict | None:  # noqa: C901
        """Override to intercept sensitive tool calls before execution.

        1. Check for a one-shot pre-approval (from a prior
           ``/daemon approve``). If found, skip the guard.
        2. Run ToolGuardEngine on the tool parameters.
        3. If findings exist:
           a. If tool is in *denied_tools*, auto-deny immediately
              (no approval offered).
           b. Otherwise, enter the approval flow so the user can
              type ``/daemon approve`` to allow execution.
        4. If no guard needed, delegate to ``super()._acting``.
        """
        if not hasattr(self, "_tool_guard_engine"):
            self._init_tool_guard()

        tool_name: str = tool_call.get("name", "")
        tool_input: dict = tool_call.get("input", {})

        try:
            if tool_name and self._should_guard_tool(tool_name):
                session_id = str(
                    self._request_context.get("session_id") or "",
                )
                if session_id:
                    consumed = (
                        await (
                            self._tool_guard_approval_service.consume_approval(
                                session_id,
                                tool_name,
                            )
                        )
                    )
                    if consumed:
                        logger.info(
                            "Tool guard: pre-approved call for '%s' "
                            "(session %s), skipping guard",
                            tool_name,
                            session_id[:8],
                        )
                        self._tool_guard_pending_info = None
                        await self._cleanup_tool_guard_denied_messages(
                            include_denial_response=True,
                        )
                        return await super()._acting(tool_call)

                result = self._tool_guard_engine.guard(tool_name, tool_input)
                if result is not None and result.findings:
                    from copaw.security.tool_guard.utils import log_findings

                    log_findings(tool_name, result)

                    if tool_name in self._tool_guard_denied_tools:
                        logger.warning(
                            "Tool guard: tool '%s' is in the denied "
                            "set, auto-denying",
                            tool_name,
                        )
                        return await self._acting_auto_denied(
                            tool_call,
                            tool_name,
                            result,
                        )

                    if self._should_require_approval():
                        return await self._acting_with_approval(
                            tool_call,
                            tool_name,
                            result,
                        )
                    # No session_id (CLI): log only, allow execution.
        except Exception as exc:
            logger.warning(
                "Tool guard check encountered an error (non-blocking): %s",
                exc,
                exc_info=True,
            )

        return await super()._acting(tool_call)

    async def _acting_auto_denied(
        self,
        tool_call,
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Auto-deny a tool call without offering approval.

        Used for tools in the *denied_tools* set when the guard engine
        detects risk.  The tool result is injected into memory so the
        LLM can see the denial, but no pending-approval record is
        created — the user cannot override via ``/daemon approve``.
        """
        from agentscope.message import ToolResultBlock
        from copaw.security.tool_guard.approval import format_findings_summary

        findings_text = format_findings_summary(guard_result)
        denied_text = (
            f"⛔ **Tool Blocked / 工具已拦截**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: `{guard_result.max_severity.value}`\n"
            f"- Findings / 发现: `{guard_result.findings_count}`\n\n"
            f"{findings_text}\n\n"
            f"This tool is blocked and cannot be approved.\n"
            f"该工具已被禁止，无法批准执行。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[{"type": "text", "text": denied_text}],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(tool_res_msg)
        return None

    async def _acting_with_approval(
        self,
        tool_call,
        tool_name: str,
        guard_result,
    ) -> dict | None:
        """Deny the tool call and record a pending approval.

        The agent loop continues with a "denied" tool result so the
        LLM can inform the user about the risk.  The user can later
        type ``/daemon approve`` to grant a one-shot approval; the
        LLM will then re-call the tool and the guard check will be
        skipped via ``consume_approval``.
        """
        from agentscope.message import ToolResultBlock
        from copaw.security.tool_guard.approval import format_findings_summary

        channel = str(self._request_context.get("channel") or "")

        for msg, marks in reversed(self.memory.content):
            if msg.role == "assistant":
                if TOOL_GUARD_DENIED_MARK not in marks:
                    marks.append(TOOL_GUARD_DENIED_MARK)
                break

        await self._tool_guard_approval_service.create_pending(
            session_id=str(self._request_context.get("session_id") or ""),
            user_id=str(self._request_context.get("user_id") or ""),
            channel=channel,
            tool_name=tool_name,
            result=guard_result,
            extra={"tool_call": tool_call},
        )

        self._tool_guard_pending_info = {
            "tool_name": tool_name,
            "tool_input": tool_call.get("input", {}),
        }

        findings_text = format_findings_summary(guard_result)
        denied_text = (
            f"⚠️ **Risk Detected / 检测到风险**\n\n"
            f"- Tool / 工具: `{tool_name}`\n"
            f"- Severity / 严重性: `{guard_result.max_severity.value}`\n"
            f"- Findings / 发现: `{guard_result.findings_count}`\n\n"
            f"{findings_text}\n\n"
            f"Type `/approve` to approve, "
            f"or send any message to deny.\n"
            f"输入 `/approve` 批准执行，或发送任意消息拒绝。"
        )

        tool_res_msg = Msg(
            "system",
            [
                ToolResultBlock(
                    type="tool_result",
                    id=tool_call["id"],
                    name=tool_name,
                    output=[{"type": "text", "text": denied_text}],
                ),
            ],
            "system",
        )

        await self.print(tool_res_msg, True)
        await self.memory.add(
            tool_res_msg,
            marks=TOOL_GUARD_DENIED_MARK,
        )
        return None

    async def _cleanup_tool_guard_denied_messages(
        self,
        include_denial_response: bool = True,
    ) -> None:
        """Remove tool-guard denied messages from memory.

        Finds messages marked with ``TOOL_GUARD_DENIED_MARK`` and
        removes them.  When *include_denial_response* is ``True``,
        also removes the assistant message immediately following the
        last marked message (the LLM's denial explanation).

        Args:
            include_denial_response: If ``True``, also remove the
                assistant denial-text response that follows the
                denied tool result.
        """
        ids_to_delete: list[str] = []
        last_marked_idx = -1

        for i, (msg, marks) in enumerate(self.memory.content):
            if TOOL_GUARD_DENIED_MARK in marks:
                ids_to_delete.append(msg.id)
                last_marked_idx = i

        if (
            include_denial_response
            and last_marked_idx >= 0
            and last_marked_idx + 1 < len(self.memory.content)
        ):
            next_msg, _ = self.memory.content[last_marked_idx + 1]
            if next_msg.role == "assistant":
                ids_to_delete.append(next_msg.id)

        if ids_to_delete:
            removed = await self.memory.delete(ids_to_delete)
            logger.info(
                "Tool guard: cleaned up %d denied message(s) from memory",
                removed,
            )

    def _last_tool_response_is_denied(self) -> bool:
        """Check if the last message is a guard-denied tool result."""
        if not self.memory.content:
            return False
        msg, marks = self.memory.content[-1]
        return TOOL_GUARD_DENIED_MARK in marks and msg.role == "system"

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Ensure a stable default tool-choice behavior across providers.

        If the last tool response was denied by the tool guard and is
        awaiting user approval, short-circuit reasoning and return a
        static message so the agent pauses until the user responds.
        """
        if self._last_tool_response_is_denied():
            pending = getattr(self, "_tool_guard_pending_info", None) or {}
            tool_name = pending.get("tool_name", "unknown")
            tool_input = pending.get("tool_input", {})
            import json as _json

            params_text = _json.dumps(
                tool_input,
                ensure_ascii=False,
                indent=2,
            )
            msg = Msg(
                self.name,
                "⏳ Waiting for approval / 等待审批\n\n"
                f"- Tool / 工具: `{tool_name}`\n"
                f"- Parameters / 参数:\n```json\n{params_text}\n```\n\n"
                "Type `/approve` to approve, "
                "or send any message to deny.\n"
                "输入 `/approve` 批准执行，或发送任意消息拒绝。",
                "assistant",
            )
            await self.print(msg, True)
            await self.memory.add(msg)
            return msg

        tool_choice = normalize_reasoning_tool_choice(
            tool_choice=tool_choice,
            has_tools=bool(self.toolkit.get_json_schemas()),
        )

        return await super()._reasoning(tool_choice=tool_choice)

    async def reply(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        """Override reply to process file blocks and handle commands.

        Args:
            msg: Input message(s) from user
            structured_model: Optional pydantic model for structured output

        Returns:
            Response message
        """
        # Process file and media blocks in messages
        if msg is not None:
            await process_file_and_media_blocks_in_message(msg)

        # Check if message is a system command
        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = (
            last_msg.get_text_content() if isinstance(last_msg, Msg) else None
        )

        if self.command_handler.is_command(query):
            logger.info(f"Received command: {query}")
            msg = await self.command_handler.handle_command(query)
            await self.print(msg)
            return msg

        # Normal message processing
        return await super().reply(msg=msg, structured_model=structured_model)

    async def interrupt(self, msg: Msg | list[Msg] | None = None) -> None:
        """Interrupt the current reply process and wait for cleanup."""
        if self._reply_task and not self._reply_task.done():
            task = self._reply_task
            task.cancel(msg)
            try:
                await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
            except Exception:
                logger.warning(
                    "Exception occurred during interrupt cleanup",
                    exc_info=True,
                )
