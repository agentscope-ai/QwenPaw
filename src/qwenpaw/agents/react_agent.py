# -*- coding: utf-8 -*-
"""QwenPaw Agent - Main agent implementation.

This module provides the main QwenPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, TYPE_CHECKING

from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from agentscope.tool import Toolkit

from anyio import ClosedResourceError

from ..app.mcp import HttpStatefulClient, StdIOStatefulClient
from .command_handler import CommandHandler
from .hooks import BootstrapHook
from .middlewares import (
    BootstrapMiddleware,
    RequestSetupMiddleware,
)
from .model_factory import create_model_and_formatter
from .tool_compat import make_tool
from .prompt import (
    build_multimodal_hint,
    build_system_prompt_from_working_dir,
)
from .skill_system import (
    ensure_skills_initialized,
    get_workspace_skills_dir,
    resolve_effective_skills,
)
from .coding_mode_mixin import CodingModeMixin
from .tools import (
    browser_use,
    delegate_external_agent,
    chat_with_agent,
    check_agent_task,
    submit_to_agent,
    desktop_screenshot,
    edit_file,
    execute_shell_command,
    get_current_time,
    get_token_usage,
    glob_search,
    grep_search,
    list_agents,
    materialize_skill,
    read_file,
    send_file_to_user,
    set_user_timezone,
    view_image,
    view_video,
    write_file,
)
from ..constant import (
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    WORKING_DIR,
)
from ..providers.model_capability_cache import get_capability_cache

if TYPE_CHECKING:
    from ..agents.memory import BaseMemoryManager
    from ..agents.context import BaseContextManager
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)

# Valid namesake strategies for tool registration
NamesakeStrategy = Literal["override", "skip", "raise", "rename"]


class QwenPawAgent(CodingModeMixin, Agent):
    """QwenPaw Agent with integrated tools, skills, and memory management.

    This agent extends agentscope 2.0 ``Agent`` with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - System command handling (/compact, /new, etc.)
    - Tool-guard security (via ``GuardedFunctionTool.check_permissions``)
    - Coding Mode features: Inline Diff (via CodingModeMixin)
    """

    def __init__(
        self,
        agent_config: "AgentProfileConfig",
        env_context: Optional[str] = None,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: BaseMemoryManager | None = None,
        context_manager: BaseContextManager | None = None,
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
            mcp_clients: Optional list of MCP clients for tool
                integration
            memory_manager: Optional memory manager instance. Pass ``None``
                to disable the memory manager entirely.
            context_manager: Optional context manager instance
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

        # Resolve effective skills once and share across toolkit /
        # skill registration.
        workspace_dir = self._workspace_dir or WORKING_DIR
        ensure_skills_initialized(workspace_dir)
        channel_name = self._request_context.get("channel", "console")
        try:
            effective_skills = resolve_effective_skills(
                workspace_dir,
                channel_name,
            )
        except Exception:  # pylint: disable=broad-except
            effective_skills = []

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit(
            effective_skills=effective_skills,
        )

        # Load and register skills
        self._register_skills(toolkit, effective_skills=effective_skills)

        # Initialize memory_manager and context_manager for use
        # in _build_sys_prompt
        self.memory_manager = memory_manager
        self.context_manager = context_manager

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
        # Attach the custom formatter to the innermost model so it
        # overrides agentscope's default formatter.
        if formatter is not None:
            innermost = model
            while hasattr(innermost, "_inner"):
                innermost = innermost._inner
            while hasattr(innermost, "_model"):
                innermost = innermost._model
            if hasattr(innermost, "formatter"):
                innermost.formatter = formatter
        middlewares = self._build_middlewares()
        init_kwargs: dict[str, Any] = {
            "name": agent_config.name or "QwenPaw",
            "model": model,
            "system_prompt": sys_prompt,
            "toolkit": toolkit,
            "react_config": ReActConfig(max_iters=running_config.max_iters),
            "middlewares": middlewares,
        }
        super().__init__(**init_kwargs)

        # Register memory tools provided by the memory manager
        if self.memory_manager is not None:
            memory_tools = self.memory_manager.list_memory_tools()
            basic_group = self.toolkit.tool_groups[0]
            for tool_fn in memory_tools:
                basic_group.tools.append(
                    make_tool(
                        tool_fn,
                        agent_id=self._agent_config.id,
                    ),
                )
            logger.debug(
                "Registered memory tools: %s",
                [fn.__name__ for fn in memory_tools],
            )

        # Tombstone for legacy ``getattr(agent, "memory", None)`` callers;
        # short-term memory itself lives on ``self.state.context``.
        self.memory = None  # type: ignore[assignment]

        # ``context_manager`` is required: it owns the dialog-path
        # resolution and the post_acting tool-result pruning hook.
        if self.context_manager is not None:
            self.command_handler = CommandHandler(
                agent_name=self.name,
                agent=self,
                memory_manager=self.memory_manager,
                context_manager=self.context_manager,
            )
        else:
            self.command_handler = None

    # Session persistence calls state_dict/load_state_dict on the agent;
    # these round-trip through self.state (AgentState pydantic model).
    def state_dict(self) -> dict:
        """Serialize the agent's 2.0 ``AgentState`` to a JSON-safe dict."""
        state = getattr(self, "state", None)
        if state is None:
            return {}
        return {"state": state.model_dump(mode="json")}

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Restore ``self.state`` from a dict produced by :meth:`state_dict`.

        Handles two formats:
        - **2.0**: ``{"state": {AgentState dump}}``
        - **1.x legacy**: ``{"memory": {"content": [[msg, marks], ...],
          "_compressed_summary": "..."}}`` — converted on-the-fly so
          existing sessions survive the upgrade.
        """
        if not isinstance(state_dict, dict):
            if strict:
                raise KeyError("state_dict is not a dict")
            return

        # --- 2.0 format (preferred) ---
        raw = state_dict.get("state")
        if raw is not None:
            try:
                self.state = AgentState.model_validate(raw)
            except Exception as exc:
                raise KeyError(
                    f"Could not load AgentState from snapshot: {exc}",
                ) from exc
            return

        # --- 1.x legacy format: migrate ``memory`` → ``state`` ---
        memory_raw = state_dict.get("memory")
        if isinstance(memory_raw, dict):
            from qwenpaw.app.runner.utils import parse_legacy_memory_state

            msgs, summary = parse_legacy_memory_state(memory_raw)
            self.state = AgentState()
            self.state.context.extend(msgs)
            self.state.summary = summary
            logger.info(
                "Migrated 1.x session: %d messages + summary(%d chars)",
                len(msgs),
                len(self.state.summary),
            )
            return

        if strict:
            raise KeyError(
                "state_dict has neither 'state' nor 'memory' key",
            )

    def _create_toolkit(
        self,
        effective_skills: list[str] | None = None,
    ) -> Toolkit:
        """Create and populate toolkit with built-in tools.

        Collects all enabled tool functions, wraps them in ``FunctionTool``
        (or ``GuardedFunctionTool`` when ``agent_id`` is set), and passes
        the list to ``Toolkit(tools=[...])`` at construction time.
        """
        effective_skills = effective_skills or []
        agent_id = self._agent_config.id

        # Check which tools are enabled from agent config
        enabled_tools: dict[str, bool] = {}
        try:
            if hasattr(self._agent_config, "tools") and hasattr(
                self._agent_config.tools,
                "builtin_tools",
            ):
                builtin_tools = self._agent_config.tools.builtin_tools
                enabled_tools = {
                    name: tool.enabled for name, tool in builtin_tools.items()
                }
        except Exception as e:
            logger.warning(
                f"Failed to load agent tools config: {e}, "
                "all tools will be disabled",
            )

        # Map of tool functions (hardcoded builtin tools)
        tool_functions: dict[str, Any] = {
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
            "delegate_external_agent": delegate_external_agent,
            "list_agents": list_agents,
            "chat_with_agent": chat_with_agent,
            "submit_to_agent": submit_to_agent,
            "check_agent_task": check_agent_task,
            **(
                {"materialize_skill": materialize_skill}
                if "make-skill" in effective_skills
                else {}
            ),
        }

        hardcoded_builtin_tools = set(tool_functions.keys())

        # Dynamically load plugin-registered tools
        from . import tools as tools_module

        plugin_tools = set()
        for tool_name in getattr(tools_module, "__all__", []):
            if tool_name not in tool_functions:
                tool_func = getattr(tools_module, tool_name, None)
                if callable(tool_func):
                    tool_functions[tool_name] = tool_func
                    plugin_tools.add(tool_name)
                    logger.debug(
                        "Discovered plugin tool: %s",
                        tool_name,
                    )

        # Build FunctionTool / GuardedFunctionTool instances
        tool_instances = []
        for tool_name, tool_func in tool_functions.items():
            if tool_name in plugin_tools:
                if tool_name not in enabled_tools:
                    logger.debug(
                        "Skipped unconfigured plugin tool: %s",
                        tool_name,
                    )
                    continue

            if not enabled_tools.get(
                tool_name,
                tool_name in hardcoded_builtin_tools,
            ):
                logger.debug("Skipped disabled tool: %s", tool_name)
                continue

            tool_instances.append(make_tool(tool_func, agent_id=agent_id))
            logger.debug("Registered tool: %s", tool_name)

        # Coding Mode tools (lsp, ast_search)
        try:
            coding_tools = self._collect_coding_mode_tools(agent_id=agent_id)
            tool_instances.extend(coding_tools)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(f"Failed to register Coding Mode tools: {e}")

        return Toolkit(tools=tool_instances)

    def _register_skills(
        self,
        toolkit: Toolkit,
        effective_skills: list[str],
    ) -> None:
        """Load and register skills from workspace directory.

        Skills are stored in ``toolkit._qp_skills`` (a dict) for downstream
        consumption (e.g. ``/skill_name`` slash commands in the runner).
        """
        if not hasattr(toolkit, "_qp_skills"):
            toolkit._qp_skills = {}  # pylint: disable=protected-access
        workspace_dir = self._workspace_dir or WORKING_DIR
        working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

        for skill_name in effective_skills:
            skill_dir = working_skills_dir / skill_name
            if skill_dir.exists():
                try:
                    # pylint: disable=protected-access
                    toolkit._qp_skills[skill_name] = {
                        "dir": str(skill_dir),
                    }
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

        sys_prompt = build_system_prompt_from_working_dir(
            working_dir=self._workspace_dir,
            agent_id=agent_id,
            heartbeat_enabled=heartbeat_enabled,
            language=self._language,
            memory_manager=self.memory_manager,
        )
        logger.debug("System prompt:\n%s...", sys_prompt[:100])

        # Inject multimodal capability awareness
        multimodal_hint = build_multimodal_hint()
        if multimodal_hint:
            sys_prompt = sys_prompt + "\n\n" + multimodal_hint

        if self._env_context is not None:
            sys_prompt = sys_prompt + "\n\n" + self._env_context

        return sys_prompt

    def _build_middlewares(self) -> list:
        """Build the middleware list for the agent constructor."""
        working_dir = (
            self._workspace_dir if self._workspace_dir else WORKING_DIR
        )
        bootstrap_hook = BootstrapHook(
            working_dir=working_dir,
            language=self._language,
        )
        mws: list = [
            # First: per-reply ContextVars + file/media block download +
            # skill env wrap.  Replaces ``QwenPawAgent.reply()`` pre-
            # processing so both ``reply()`` and ``reply_stream()`` get
            # the same setup (5 ContextVars + process_file_and_media_blocks +
            # apply_skill_config_env_overrides).
            RequestSetupMiddleware(
                workspace_dir=self._workspace_dir,
                agent_id=self._agent_config.id,
                agent_config=self._agent_config,
                request_context=self._request_context,
            ),
            BootstrapMiddleware(bootstrap_hook),
        ]
        if self.context_manager is not None:
            # ``BaseContextManager`` itself inherits from
            # ``MiddlewareBase`` — no wrapper needed.
            mws.append(self.context_manager)
        logger.debug("Built %d middleware(s)", len(mws))
        return mws

    def rebuild_sys_prompt(self) -> None:
        """Rebuild and replace the system prompt.

        Useful after load_session_state to ensure the prompt reflects
        the latest AGENTS.md / SOUL.md / PROFILE.md on disk.

        Updates both self._system_prompt and the first system-role
        message stored in ``self.state.context`` (if one exists).
        """
        self._system_prompt = self._build_sys_prompt()

        for msg in self.state.context:
            if msg.role == "system":
                msg.content = self._system_prompt
            break

    async def register_mcp_clients(self) -> None:
        """Register MCP clients on this agent's toolkit after construction.

        Appends each MCP client directly to the toolkit's basic tool group.
        """
        basic_group = self.toolkit.tool_groups[0]
        for i, client in enumerate(self._mcp_clients):
            client_name = getattr(client, "name", repr(client))
            try:
                if client not in basic_group.mcps:
                    basic_group.mcps.append(client)
                    logger.debug("Registered MCP client '%s'", client_name)
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
                        if recovered_client not in basic_group.mcps:
                            basic_group.mcps.append(recovered_client)
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
    _MEDIA_MIME_PREFIXES = ("image/", "audio/", "video/")

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

    # _auto_continue_if_text_only — replaced by inline logic in _reasoning()
    # which leverages the 2.0 outer react loop instead of a manual while-loop.

    def _get_model_key(self) -> str | None:
        """Return the capability-cache key for the active model."""
        model = getattr(self, "model", None)
        return getattr(model, "model_key", None)

    def _model_rejects_media(self) -> bool:
        """Check the capability cache for a learned ``rejects_media`` flag."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_media", False)

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

    # pylint: disable=too-many-branches,too-many-statements
    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ):
        """Forward 2.0 ``_reasoning`` events with proactive media
        stripping, passive bad-request retry, and auto-continue on
        text-only responses."""

        # ── Proactive media stripping ──
        from .model_factory import _supports_multimodal_for_current_model

        should_strip = (
            not _supports_multimodal_for_current_model()
            or self._model_rejects_media()
        )
        if should_strip:
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) before "
                        "_reasoning (model lacks multimodal support).",
                        n,
                    )

        # ── Model call with passive retry on media error ──
        final_msg: Msg | None = None
        try:
            async for evt in super()._reasoning(tool_choice=tool_choice):
                if isinstance(evt, Msg):
                    final_msg = evt
                else:
                    yield evt
        except Exception as e:
            if not self._is_bad_request_or_media_error(e):
                raise

            model_key = self._get_model_key()
            if model_key:
                get_capability_cache().learn(
                    model_key,
                    "rejects_media",
                    True,
                )
            logger.warning(
                "_reasoning failed with media error (%s); "
                "stripping media and retrying.",
                e,
            )
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                self._strip_media_blocks_from_memory()

            try:
                async for evt in super()._reasoning(
                    tool_choice=tool_choice,
                ):
                    if isinstance(evt, Msg):
                        final_msg = evt
                    else:
                        yield evt
            finally:
                if self._uses_request_time_media_normalization():
                    self._set_formatter_media_strip(False)
        else:
            if should_strip and self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(False)

        if final_msg is None:
            return

        # ── Auto-continue: text-only → inject hint, let outer loop retry ──
        if self._should_auto_continue(final_msg, tool_choice):
            hint_body = self._auto_continue_system_hint()
            tail = self._auto_continue_tail_context(
                final_msg,
                self._AUTO_CONTINUE_TAIL_CHARS,
            )
            if tail:
                hint_body += (
                    "\n\n<previous-assistant-tail>\n"
                    f"{tail}\n"
                    "</previous-assistant-tail>"
                )
            logger.info(
                "Auto-continue: text-only response; injecting hint "
                "(tool_choice=%r)",
                tool_choice,
            )
            self.state.context.append(
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=hint_body)],
                ),
            )
            return  # outer loop continues → _check_next_action → reasoning

        yield final_msg

    def _should_auto_continue(
        self,
        msg: Msg,
        tool_choice: Literal["auto", "none", "required"] | None,
    ) -> bool:
        """Check if auto-continue should be triggered."""
        running = getattr(self, "_agent_config", None)
        running = getattr(running, "running", None)
        if running is None or not getattr(
            running,
            "auto_continue_on_text_only",
            False,
        ):
            return False

        if msg is None or msg.has_content_blocks("tool_call"):
            return False

        if tool_choice == "none":
            return False

        if self.state.cur_iter >= self.react_config.max_iters - 1:
            return False

        return True

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

    def _is_media_block(self, block: Any) -> bool:
        """Return True if *block* carries image/audio/video data."""
        if isinstance(block, dict):
            return block.get("type") in self._MEDIA_BLOCK_TYPES
        btype = getattr(block, "type", None)
        if btype in self._MEDIA_BLOCK_TYPES:
            return True
        if btype == "data":
            source = getattr(block, "source", None)
            mt = getattr(source, "media_type", "") or ""
            return mt.startswith(self._MEDIA_MIME_PREFIXES)
        return False

    # pylint: disable=too-many-nested-blocks
    def _strip_media_blocks_from_memory(self) -> int:
        """Remove media blocks (image/audio/video/DataBlock) from all messages.

        Also strips media blocks nested inside ToolResultBlock outputs.
        Inserts placeholder text when stripping leaves content empty to
        avoid malformed API requests.

        Returns:
            Total number of media blocks removed.
        """
        total_stripped = 0

        for msg in self.state.context:
            if not isinstance(msg.content, list):
                continue

            new_content = []
            stripped_this_message = 0
            for block in msg.content:
                if self._is_media_block(block):
                    total_stripped += 1
                    stripped_this_message += 1
                    continue

                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "tool_result":
                    output = (
                        block.get("output")
                        if isinstance(block, dict)
                        else getattr(block, "output", None)
                    )
                    if isinstance(output, list):
                        filtered = [
                            item
                            for item in output
                            if not self._is_media_block(item)
                        ]
                        stripped_count = len(output) - len(filtered)
                        total_stripped += stripped_count
                        stripped_this_message += stripped_count
                        if stripped_count > 0:
                            if isinstance(block, dict):
                                block["output"] = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )
                            else:
                                block.output = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    TextBlock(type="text", text=MEDIA_UNSUPPORTED_PLACEHOLDER),
                )

            msg.content = new_content

        return total_stripped
