# -*- coding: utf-8 -*-
"""QwenPaw Agent - Main agent implementation.

This module provides the main QwenPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, Type, TYPE_CHECKING

from agentscope.agent import ReActAgent
from agentscope.agent._react_agent import _MemoryMark
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg
from agentscope.tool import Toolkit
from anyio import ClosedResourceError
from pydantic import BaseModel

from ..app.mcp import HttpStatefulClient, StdIOStatefulClient
from .command_handler import CommandHandler
from .hooks import BootstrapHook, MemoryCompactionHook
from .model_factory import create_model_and_formatter
from .prompt import (
    build_multimodal_hint,
    build_system_prompt_from_working_dir,
    get_active_model_supports_multimodal,
)
from .skills_manager import (
    apply_skill_config_env_overrides,
    ensure_skills_initialized,
    get_workspace_skills_dir,
    resolve_effective_skills,
)
from .tool_guard_mixin import ToolGuardMixin
from .tools import (
    browser_use,
    chat_with_agent,
    desktop_screenshot,
    edit_file,
    execute_shell_command,
    get_current_time,
    get_token_usage,
    glob_search,
    grep_search,
    list_agents,
    read_file,
    send_file_to_user,
    set_user_timezone,
    view_image,
    view_video,
    write_file,
    create_memory_search_tool,
)
from .utils import process_file_and_media_blocks_in_message
from ..constant import (
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    WORKING_DIR,
)
from ..agents.memory import BaseMemoryManager

if TYPE_CHECKING:
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)

# Valid namesake strategies for tool registration
NamesakeStrategy = Literal["override", "skip", "raise", "rename"]


class QwenPawAgent(ToolGuardMixin, ReActAgent):
    """QwenPaw Agent with integrated tools, skills, and memory management.

    This agent extends ReActAgent with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - System command handling (/compact, /new, etc.)
    - Tool-guard security interception (via ToolGuardMixin)

    MRO note
    ~~~~~~~~
    ``ToolGuardMixin`` overrides ``_acting`` and ``_reasoning`` via
    Python's MRO: QwenPawAgent → ToolGuardMixin → ReActAgent.  If you
    add a ``_acting`` or ``_reasoning`` override in this class, you
    **must** call ``super()._acting(...)`` / ``super()._reasoning(...)``
    so the guard interception remains active.
    """

    def __init__(
        self,
        agent_config: "AgentProfileConfig",
        env_context: Optional[str] = None,
        enable_memory_manager: bool = True,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: "BaseMemoryManager | None" = None,
        request_context: Optional[dict[str, str]] = None,
        namesake_strategy: NamesakeStrategy = "skip",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
    ):
        """Initialize QwenPawAgent.

        Args:
            agent_config: Agent profile configuration containing all settings
                including running config (max_iters, max_input_length,
                memory_compact_threshold, etc.) and language setting.
            env_context: Optional environment context to prepend to
                system prompt
            enable_memory_manager: Whether to enable memory manager
            mcp_clients: Optional list of MCP clients for tool
                integration
            memory_manager: Optional memory manager instance
            request_context: Optional request context with session_id,
                user_id, channel, agent_id
            namesake_strategy: Strategy to handle namesake tool functions.
                Options: "override", "skip", "raise", "rename"
                (default: "skip")
            workspace_dir: Workspace directory for reading prompt files
                (if None, uses global WORKING_DIR)
        """
        self._agent_config = agent_config
        self._env_context = env_context
        self._request_context = dict(request_context or {})
        self._mcp_clients = mcp_clients or []
        self._namesake_strategy = namesake_strategy
        self._workspace_dir = workspace_dir
        self._task_tracker = task_tracker

        # Extract configuration from agent_config
        running_config = agent_config.running
        self._language = agent_config.language

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit(namesake_strategy=namesake_strategy)

        # Load and register skills
        self._register_skills(toolkit)

        # Build system prompt
        sys_prompt = self._build_sys_prompt()

        # Create model and formatter using factory method
        model, formatter = create_model_and_formatter(agent_id=agent_config.id)
        model_info = (
            f"{agent_config.active_model.provider_id}/"
            f"{agent_config.active_model.model}"
            if agent_config.active_model
            else "global-fallback"
        )
        logger.info(
            f"Agent '{agent_config.id}' initialized with model: "
            f"{model_info} (class: {model.__class__.__name__})",
        )
        # Initialize parent ReActAgent
        super().__init__(
            name="Friday",
            model=model,
            sys_prompt=sys_prompt,
            toolkit=toolkit,
            memory=InMemoryMemory(),
            formatter=formatter,
            max_iters=running_config.max_iters,
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

        # Check which tools are enabled from agent config
        enabled_tools = {}
        async_execution_tools = {}
        try:
            if hasattr(self._agent_config, "tools") and hasattr(
                self._agent_config.tools,
                "builtin_tools",
            ):
                builtin_tools = self._agent_config.tools.builtin_tools
                enabled_tools = {
                    name: tool.enabled for name, tool in builtin_tools.items()
                }
                # Only execute_shell_command supports async_execution
                async_execution_tools = {
                    "execute_shell_command": builtin_tools.get(
                        "execute_shell_command",
                    ).async_execution
                    if "execute_shell_command" in builtin_tools
                    else False,
                }
        except Exception as e:
            logger.warning(
                f"Failed to load agent tools config: {e}, "
                "all tools will be disabled",
            )

        # Map of tool functions
        tool_functions = {
            "execute_shell_command": execute_shell_command,
            "read_file": read_file,
            "write_file": write_file,
            "edit_file": edit_file,
            "grep_search": grep_search,
            "glob_search": glob_search,
            "browser_use": browser_use,
            "desktop_screenshot": desktop_screenshot,
            "view_image": view_image,
            "view_video": view_video,
            "send_file_to_user": send_file_to_user,
            "get_current_time": get_current_time,
            "set_user_timezone": set_user_timezone,
            "get_token_usage": get_token_usage,
            "list_agents": list_agents,
            "chat_with_agent": chat_with_agent,
        }

        multimodal = get_active_model_supports_multimodal()

        # Register only enabled tools
        for tool_name, tool_func in tool_functions.items():
            # If tool not in config, enable by default (backward compatibility)
            if not enabled_tools.get(tool_name, True):
                logger.debug("Skipped disabled tool: %s", tool_name)
                continue

            if tool_name in ("view_image", "view_video") and not multimodal:
                logger.debug(
                    "Skipped %s — model does not support multimodal",
                    tool_name,
                )
                continue

            # Get async_execution setting (default to False for backward
            # compatibility)
            async_exec = async_execution_tools.get(tool_name, False)

            toolkit.register_tool_function(
                tool_func,
                namesake_strategy=namesake_strategy,
                async_execution=async_exec,
            )
            logger.debug(
                "Registered tool: %s (async_execution=%s)",
                tool_name,
                async_exec,
            )

        # Auto-register background task management tools if any *enabled*
        # tool has async_execution set
        has_async_tools = any(
            async_execution_tools.get(name, False)
            for name in tool_functions
            if enabled_tools.get(name, True)
        )
        if has_async_tools:
            try:
                toolkit.register_tool_function(
                    toolkit.view_task,
                    namesake_strategy=namesake_strategy,
                )
                toolkit.register_tool_function(
                    toolkit.wait_task,
                    namesake_strategy=namesake_strategy,
                )
                toolkit.register_tool_function(
                    toolkit.cancel_task,
                    namesake_strategy=namesake_strategy,
                )
                logger.debug(
                    "Registered background task management tools "
                    "(view_task, wait_task, cancel_task)",
                )
            except Exception as e:
                logger.warning(
                    f"Failed to register task management tools: {e}",
                )

        return toolkit

    def _register_skills(self, toolkit: Toolkit) -> None:
        """Load and register skills from workspace directory.

        Uses the registry-backed skill resolver to determine effective
        skills for the current channel.

        Args:
            toolkit: Toolkit to register skills to
        """
        workspace_dir = self._workspace_dir or WORKING_DIR

        ensure_skills_initialized(workspace_dir)

        request_context = getattr(self, "_request_context", {})
        channel_name = request_context.get("channel", "console")

        effective_skills = resolve_effective_skills(
            workspace_dir,
            channel_name,
        )

        working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

        for skill_name in effective_skills:
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
        # Get agent_id from request_context
        agent_id = (
            self._request_context.get("agent_id")
            if self._request_context
            else None
        )

        # Check if heartbeat is enabled in agent config
        heartbeat_enabled = False
        if (
            hasattr(self._agent_config, "heartbeat")
            and self._agent_config.heartbeat is not None
        ):
            heartbeat_enabled = self._agent_config.heartbeat.enabled

        # Check if memory prompt is enabled in agent config
        memory_prompt_enabled = True
        try:
            memory_prompt_enabled = (
                self._agent_config.running.memory_summary.memory_prompt_enabled
            )
        except AttributeError:
            pass

        sys_prompt = build_system_prompt_from_working_dir(
            working_dir=self._workspace_dir,
            agent_id=agent_id,
            heartbeat_enabled=heartbeat_enabled,
            memory_prompt_enabled=memory_prompt_enabled,
        )
        logger.debug("System prompt:\n%s...", sys_prompt[:100])

        # Inject multimodal capability awareness
        multimodal_hint = build_multimodal_hint()
        if multimodal_hint:
            sys_prompt = sys_prompt + "\n\n" + multimodal_hint

        if self._env_context is not None:
            sys_prompt = sys_prompt + "\n\n" + self._env_context

        return sys_prompt

    def _setup_memory_manager(
        self,
        enable_memory_manager: bool,
        memory_manager: BaseMemoryManager | None,
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
        # Use workspace_dir if available, else fallback to WORKING_DIR
        working_dir = (
            self._workspace_dir if self._workspace_dir else WORKING_DIR
        )
        bootstrap_hook = BootstrapHook(
            working_dir=working_dir,
            language=self._language,
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

        if self.memory is None:
            logger.warning(
                "rebuild_sys_prompt: self.memory is None, "
                "skipping in-memory system prompt update.",
            )
            return

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
                logger.warning(
                    "Failed to register MCP client '%s', skipping: %s",
                    client_name,
                    e,
                    exc_info=True,
                )

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
        rebuild_info = getattr(client, "_qwenpaw_rebuild_info", None)
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
                setattr(rebuilt_client, "_qwenpaw_rebuild_info", rebuild_info)
                return rebuilt_client

            raw_headers = rebuild_info.get("headers") or {}
            headers = (
                {k: os.path.expandvars(v) for k, v in raw_headers.items()}
                if raw_headers
                else None
            )
            rebuilt_client = HttpStatefulClient(
                name=name,
                transport=transport,
                url=rebuild_info.get("url"),
                headers=headers,
            )
            setattr(rebuilt_client, "_qwenpaw_rebuild_info", rebuild_info)
            return rebuilt_client
        except Exception:  # pylint: disable=broad-except
            return None

    # ------------------------------------------------------------------
    # Media-block fallback: strip unsupported media blocks (image, audio,
    # video) from memory and retry when the model rejects them.
    # ------------------------------------------------------------------

    _MEDIA_BLOCK_TYPES = {"image", "audio", "video"}

    _AUTO_CONTINUE_MAX_EXTRA = 2
    _AUTO_CONTINUE_TAIL_CHARS = 600

    _AUTO_CONTINUE_HINT_EN = (
        "<system-hint>"
        "Your previous assistant turn had text only (no tool calls). "
        "Use the trailing excerpt in <previous-assistant-tail> (if present) "
        "plus the conversation to decide in this **reasoning** step: if the "
        "user's task still needs tools, emit tool_use now; if it is fully "
        "done, reply with a short text only (no tools). "
        "Do not stop with plans or code fences alone when tools are still "
        "needed."
        "</system-hint>"
    )
    _AUTO_CONTINUE_HINT_ZH = (
        "<system-hint>"
        "上轮助手仅文字、未调工具。请结合上下文与 <previous-assistant-tail> "
        "（若有）在本轮推理中判断：仍需执行则立刻 tool；已完结则简短收尾。"
        "需要操作时勿只输出计划或代码块。"
        "</system-hint>"
    )

    def _auto_continue_system_hint(self) -> str:
        """Pick hint by agent language (zh vs others)."""
        raw_lang = getattr(self._agent_config, "language", None)
        lang = (raw_lang or "").strip().lower()
        if lang == "zh":
            return self._AUTO_CONTINUE_HINT_ZH
        return self._AUTO_CONTINUE_HINT_EN

    @staticmethod
    def _auto_continue_tail_context(msg: Msg, max_chars: int) -> str:
        """Assistant text suffix for hint (fixed cut, not sentence NLP)."""
        raw = msg.get_text_content() if msg is not None else ""
        text = (raw or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[-max_chars:].lstrip()

    async def _auto_continue_if_text_only(
        self,
        msg: Msg,
        tool_choice: Literal["auto", "none", "required"] | None,
    ) -> Msg:
        """Nudge the model when it returns text-only mid-task.

        Injects a language-matched hint (with a trailing excerpt of the
        assistant text for self-review) and runs up to
        ``_AUTO_CONTINUE_MAX_EXTRA`` extra ``_reasoning`` passes until a
        tool_use appears or the cap is
        hit.  Uses the original ``tool_choice`` unchanged (no switching).
        If an extra pass still returns text-only, keep the prior response to
        avoid repeated duplicated answers.
        """
        running = self._agent_config.running
        if not running.auto_continue_on_text_only:
            return msg
        if msg is None or msg.has_content_blocks("tool_use"):
            return msg

        extra = 0
        while extra < self._AUTO_CONTINUE_MAX_EXTRA:
            if msg.has_content_blocks("tool_use"):
                break
            extra += 1
            tail = self._auto_continue_tail_context(
                msg,
                self._AUTO_CONTINUE_TAIL_CHARS,
            )
            hint_body = self._auto_continue_system_hint()
            if tail:
                hint_body += (
                    "\n\n<previous-assistant-tail>\n"
                    f"{tail}\n"
                    "</previous-assistant-tail>"
                )
            logger.info(
                "Auto-continue: text-only (%d/%d); hint + _reasoning "
                "tool_choice=%r",
                extra,
                self._AUTO_CONTINUE_MAX_EXTRA,
                tool_choice,
            )
            hint_msg = Msg("user", hint_body, "user")
            await self.memory.add(hint_msg, marks=_MemoryMark.HINT)
            try:
                next_msg = await super()._reasoning(tool_choice=tool_choice)
            except Exception:
                logger.warning(
                    "Auto-continue extra _reasoning failed; "
                    "keeping prior response",
                    exc_info=True,
                )
                break
            if next_msg.has_content_blocks("tool_use"):
                msg = next_msg
                continue
            logger.info(
                "Auto-continue extra _reasoning still text-only; "
                "keeping prior response",
            )
            break

        return msg

    def _proactive_strip_media_blocks(self) -> int:
        """Proactively strip media blocks from memory before model call.

        Only called when the active model does not support multimodal.
        Returns the number of blocks stripped.
        """
        return self._strip_media_blocks_from_memory()

    def _uses_request_time_media_normalization(self) -> bool:
        """Return True when request-time normalization can handle media."""
        return getattr(self, "formatter", None) is not None

    def _set_formatter_media_strip(self, enabled: bool) -> None:
        """Toggle request-time media stripping on the active formatter."""
        formatter = getattr(self, "formatter", None)
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_media", enabled)

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Override reasoning with proactive media filtering.

        1. Proactive layer: if the model does not support
           multimodal, strip media blocks *before* calling.
        2. Passive layer: if the model call still fails with a
           bad-request / media error, strip remaining blocks and retry.
        3. If the model IS marked as multimodal but still errors on
           media, log a warning about possibly inaccurate capability flag.

        Calls ``super()._reasoning`` to keep the ToolGuardMixin
        interception active.
        """
        # --- Proactive filtering layer ---
        if not get_active_model_supports_multimodal():
            if self._uses_request_time_media_normalization():
                logger.debug(
                    "Formatter will strip media from copied messages "
                    "before reasoning.",
                )
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) - "
                        "model does not support multimodal.",
                        n,
                    )

        # --- Passive fallback layer (existing logic) ---
        try:
            msg = await super()._reasoning(tool_choice=tool_choice)
        except Exception as e:
            if not self._is_bad_request_or_media_error(e):
                raise

            if self._uses_request_time_media_normalization():
                if get_active_model_supports_multimodal():
                    logger.warning(
                        "Model marked multimodal but "
                        "rejected media. "
                        "Capability flag may be wrong.",
                    )
                self._set_formatter_media_strip(True)
                try:
                    logger.warning(
                        "_reasoning failed (%s). "
                        "Retrying with request-time media stripping.",
                        e,
                    )
                    return await super()._reasoning(tool_choice=tool_choice)
                finally:
                    self._set_formatter_media_strip(False)

            n_stripped = self._strip_media_blocks_from_memory()
            if n_stripped == 0:
                raise

            # If the model is marked as multimodal but still
            # errored, the capability flag may be wrong.
            if get_active_model_supports_multimodal():
                logger.warning(
                    "Model marked multimodal but "
                    "rejected media. "
                    "Capability flag may be wrong.",
                )

            logger.warning(
                "_reasoning failed (%s). "
                "Stripped %d media block(s) from memory, retrying.",
                e,
                n_stripped,
            )
            msg = await super()._reasoning(tool_choice=tool_choice)

        return await self._auto_continue_if_text_only(msg, tool_choice)

    # pylint: disable=too-many-branches
    async def _summarizing(self) -> Msg:
        """Override summarizing with proactive media filtering,
        passive fallback, and tool_use block filtering.

        1. Proactive layer: if the model does not support multimodal,
           strip media blocks *before* calling the model.
        2. Passive layer: if the model call still fails with a
           bad-request / media error, strip remaining blocks and retry.
        3. If the model IS marked as multimodal but still errors on
           media, log a warning about possibly inaccurate capability flag.

        Some models (e.g. kimi-k2.5) generate tool_use blocks even when
        no tools are provided.  We set ``_in_summarizing`` so that
        ``print`` can strip tool_use blocks from streaming chunks.
        """
        # --- Proactive filtering layer ---
        if not get_active_model_supports_multimodal():
            if self._uses_request_time_media_normalization():
                logger.debug(
                    "Formatter will strip media from copied messages "
                    "before summarizing.",
                )
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) - "
                        "model does not support multimodal.",
                        n,
                    )

        # --- Passive fallback layer ---
        self._in_summarizing = True
        try:
            try:
                msg = await super()._summarizing()
            except Exception as e:
                if not self._is_bad_request_or_media_error(e):
                    raise

                if self._uses_request_time_media_normalization():
                    if get_active_model_supports_multimodal():
                        logger.warning(
                            "Model marked multimodal but "
                            "rejected media. "
                            "Capability flag may be wrong.",
                        )
                    self._set_formatter_media_strip(True)
                    try:
                        logger.warning(
                            "_summarizing failed (%s). "
                            "Retrying with request-time media stripping.",
                            e,
                        )
                        msg = await super()._summarizing()
                    finally:
                        self._set_formatter_media_strip(False)
                else:
                    n_stripped = self._strip_media_blocks_from_memory()
                    if n_stripped == 0:
                        raise

                    if get_active_model_supports_multimodal():
                        logger.warning(
                            "Model marked multimodal but "
                            "rejected media. "
                            "Capability flag may be wrong.",
                        )

                    logger.warning(
                        "_summarizing failed (%s). "
                        "Stripped %d media block(s) from memory, retrying.",
                        e,
                        n_stripped,
                    )
                    msg = await super()._summarizing()
        finally:
            self._in_summarizing = False

        return self._strip_tool_use_from_msg(msg)

    async def print(
        self,
        msg: Msg,
        last: bool = True,
        speech: Any = None,
    ) -> None:
        """Filter tool_use blocks during _summarizing before they hit the
        message queue, preventing the frontend from briefly rendering
        phantom tool calls that will never be executed.

        On the *final* streaming event (``last=True``), append the
        round-end notice so users see it immediately instead of only
        after a page refresh.  Intermediate events that become empty
        after filtering are silently skipped to avoid blank UI flashes.
        """

        if not getattr(self, "_in_summarizing", False):
            return await super().print(msg, last, speech=speech)

        original = msg.content
        modified = False

        if isinstance(original, list):
            filtered = [
                b
                for b in original
                if not (isinstance(b, dict) and b.get("type") == "tool_use")
            ]
            if not filtered and not last:
                return
            if len(filtered) != len(original) or last:
                msg.content = filtered
                if last:
                    msg.content.append(
                        {"type": "text", "text": self._ROUND_END_NOTICE},
                    )
                modified = True
        elif isinstance(original, str) and last:
            msg.content = original + self._ROUND_END_NOTICE
            modified = True
        if modified:
            try:
                return await super().print(msg, last, speech=speech)
            finally:
                msg.content = original
        return await super().print(msg, last, speech=speech)

    _ROUND_END_NOTICE = (
        "\n\n---\n"
        "本轮调用已达最大次数，回复已终止，请继续输入。\n"
        "Maximum iterations reached for this round. "
        "Please send a new message to continue."
    )

    @staticmethod
    def _strip_tool_use_from_msg(msg: Msg) -> Msg:
        """Remove tool_use blocks from a message and append a user notice.

        When _summarizing is called without tools, some models still
        return tool_use blocks.  Those blocks can never be executed, so
        strip them and append a bilingual notice telling the user this
        round of calls has ended.
        """
        if isinstance(msg.content, str):
            msg.content += QwenPawAgent._ROUND_END_NOTICE
            return msg

        filtered = [
            block
            for block in msg.content
            if not (
                isinstance(block, dict) and block.get("type") == "tool_use"
            )
        ]

        n_removed = len(msg.content) - len(filtered)
        if n_removed:
            logger.debug(
                "Stripped %d tool_use block(s) from _summarizing response",
                n_removed,
            )

        filtered.append(
            {"type": "text", "text": QwenPawAgent._ROUND_END_NOTICE},
        )
        msg.content = filtered
        return msg

    @staticmethod
    def _is_bad_request_or_media_error(exc: Exception) -> bool:
        """Return True for 400-class or media-related model errors.

        Targets bad-request (400) errors because unsupported media
        content typically causes request validation failures.  Keyword
        matching provides an extra safety net for providers that use
        non-standard status codes.
        """
        status = getattr(exc, "status_code", None)
        if status == 400:
            return True

        error_str = str(exc).lower()
        keywords = [
            "image",
            "audio",
            "video",
            "vision",
            "multimodal",
            "image_url",
        ]
        return any(kw in error_str for kw in keywords)

    def _strip_media_blocks_from_memory(self) -> int:
        """Remove media blocks (image/audio/video) from all messages.

        Also strips media blocks nested inside ToolResultBlock outputs.
        Inserts placeholder text when stripping leaves content empty to
        avoid malformed API requests.

        Returns:
            Total number of media blocks removed.
        """
        media_types = self._MEDIA_BLOCK_TYPES
        total_stripped = 0

        for msg, _marks in self.memory.content:
            if not isinstance(msg.content, list):
                continue

            new_content = []
            stripped_this_message = 0
            for block in msg.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") in media_types
                ):
                    total_stripped += 1
                    stripped_this_message += 1
                    continue

                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and isinstance(block.get("output"), list)
                ):
                    original_len = len(block["output"])
                    block["output"] = [
                        item
                        for item in block["output"]
                        if not (
                            isinstance(item, dict)
                            and item.get("type") in media_types
                        )
                    ]
                    stripped_count = original_len - len(block["output"])
                    total_stripped += stripped_count
                    stripped_this_message += stripped_count
                    if stripped_count > 0 and not block["output"]:
                        block["output"] = MEDIA_UNSUPPORTED_PLACEHOLDER

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    {
                        "type": "text",
                        "text": MEDIA_UNSUPPORTED_PLACEHOLDER,
                    },
                )

            msg.content = new_content

        return total_stripped

    # pylint: disable=protected-access
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
        # Set workspace_dir and recent_max_bytes in context for tool functions
        from ..config.context import (
            set_current_workspace_dir,
            set_current_recent_max_bytes,
        )

        set_current_workspace_dir(self._workspace_dir)
        set_current_recent_max_bytes(
            self._agent_config.running.tool_result_compact.recent_max_bytes,
        )

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
        logger.info("QwenPawAgent.reply: max_iters=%s", self.max_iters)

        if hasattr(self.memory, "_long_term_memory"):
            running = self._agent_config.running
            ms = running.memory_summary
            if (
                ms.force_memory_search
                and self.memory_manager is not None
                and query
            ):
                try:
                    result = await asyncio.wait_for(
                        self.memory_manager.memory_search(
                            query=query[:100],
                            max_results=ms.force_max_results,
                            min_score=ms.force_min_score,
                        ),
                        timeout=ms.force_memory_search_timeout,
                    )
                    self.memory._long_term_memory = "\n".join(
                        block["text"]
                        for block in (result.content or [])
                        if isinstance(block, dict) and block.get("text")
                    )
                except BaseException as e:
                    logger.warning(
                        "force_memory_search failed or timed out,"
                        f" skipping e={e}",
                    )
                    self.memory._long_term_memory = ""
            else:
                self.memory._long_term_memory = ""

        request_context = getattr(self, "_request_context", {}) or {}
        channel_name = request_context.get("channel", "console")
        workspace_dir = Path(self._workspace_dir or WORKING_DIR)
        with apply_skill_config_env_overrides(workspace_dir, channel_name):
            return await super().reply(
                msg=msg,
                structured_model=structured_model,
            )

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
