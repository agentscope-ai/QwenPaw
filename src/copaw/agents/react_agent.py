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
from agentscope.message import Msg
from agentscope.tool import Toolkit
from pydantic import BaseModel

from .command_handler import CommandHandler
from .hooks import BootstrapHook, MemoryCompactionHook
from .memory import CoPawInMemoryMemory
from .model_factory import ModelManager, create_model_and_formatter
from .prompt import build_system_prompt_from_working_dir
from .skills_manager import (
    ensure_skills_initialized,
    get_working_skills_dir,
    list_available_skills,
)
from .task_router import TaskRouter
from .tools import (
    browser_use,
    create_memory_search_tool,
    desktop_screenshot,
    edit_file,
    execute_shell_command,
    get_current_time,
    read_file,
    send_file_to_user,
    write_file,
)
from .utils import process_file_and_media_blocks_in_message
from ..agents.memory import MemoryManager
from ..config import load_config
from ..constant import (
    MEMORY_COMPACT_KEEP_RECENT,
    MEMORY_COMPACT_RATIO,
    WORKING_DIR,
)
from ..providers import get_routing_enabled

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
    - Intelligent task routing for tier-based model selection
    """

    def __init__(
        self,
        env_context: Optional[str] = None,
        enable_memory_manager: bool = True,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: MemoryManager | None = None,
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
        self._max_input_length = max_input_length
        self._mcp_clients = mcp_clients or []
        self._namesake_strategy = namesake_strategy

        # Memory compaction threshold: configurable ratio of max_input_length
        self._memory_compact_threshold = int(
            max_input_length * MEMORY_COMPACT_RATIO,
        )

        # Initialize task router for intelligent model selection
        self.task_router = TaskRouter()
        
        # Initialize lock for concurrency safety
        self._model_swap_lock = asyncio.Lock()

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
            memory=CoPawInMemoryMemory(),
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
            formatter=self.formatter,  # type: ignore[has-type]
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

        # Register built-in tools
        toolkit.register_tool_function(
            execute_shell_command,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            read_file,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            write_file,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            edit_file,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            browser_use,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            desktop_screenshot,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            send_file_to_user,
            namesake_strategy=namesake_strategy,
        )
        toolkit.register_tool_function(
            get_current_time,
            namesake_strategy=namesake_strategy,
        )

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
            self.memory_manager.chat_model = (
                self.model  # type: ignore[has-type]
            )
            self.memory_manager.formatter = (
                self.formatter  # type: ignore[has-type]
            )

            memory_search_tool = create_memory_search_tool(self.memory_manager)
            self.toolkit.register_tool_function(
                memory_search_tool,
                namesake_strategy=namesake_strategy,
            )
            logger.debug("Registered memory_search tool")

    def _register_hooks(self) -> None:
        """Register pre-reasoning hooks for bootstrap and memory compaction."""
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
                memory_compact_threshold=self._memory_compact_threshold,
                keep_recent=MEMORY_COMPACT_KEEP_RECENT,
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
        for client in self._mcp_clients:
            await self.toolkit.register_mcp_client(
                client,
                namesake_strategy=namesake_strategy,
            )

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        """Ensure a stable default tool-choice behavior across providers."""
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

        Also handles intelligent task routing for tier-based model selection.

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

        # Intelligent task routing
        tier = None
        cleaned_query = query
        if query:
            # Parse force-override prefix
            override_tier, cleaned_query = self.task_router.parse_override(
                query,
            )

            # Check if routing is enabled (read live config)
            routing_enabled = get_routing_enabled()

            if override_tier:
                # User explicitly requested a tier
                tier = override_tier
                if cleaned_query != query and last_msg:
                    last_msg.content = cleaned_query
                logger.info(f"Task routing: tier={tier} (user override)")
            elif routing_enabled:
                # Auto-classify task
                tier = self.task_router.classify_task(
                    query,
                    self.toolkit.tools
                    if hasattr(self.toolkit, "tools")
                    else [],
                    self.memory.content
                    if hasattr(self.memory, "content")
                    else [],
                )
                logger.info(f"Task routing: tier={tier} (auto-classified)")
            else:
                logger.debug("Task routing: disabled, using default model")

        # Apply tier-based model selection if tier determined
        # Use lock to ensure concurrency safety for the entire reply execution
        async with self._model_swap_lock:
            original_model = None
            original_formatter = None
            if tier:
                try:
                    new_model, new_formatter = ModelManager.get_model_for_tier(
                        tier,
                    )
                    # pylint: disable=access-member-before-definition
                    original_model = self.model  # type: ignore[has-type]
                    original_formatter = self.formatter  # type: ignore[has-type]
                    self.model = new_model  # type: ignore[has-type]
                    self.formatter = new_formatter  # type: ignore[has-type]
                    logger.debug(
                        f"Switched to model for tier '{tier}': "
                        f"{new_model.model_name}",
                    )
                except ValueError as e:
                    # Handle known error cases that should trigger fallback
                    logger.warning(
                        f"Failed to get model for tier '{tier}': {e}, "
                        "using default model",
                    )
                    tier = None
                except Exception as e:
                    # Handle unexpected errors with full stack trace
                    logger.exception(
                        f"Unexpected error getting model for tier '{tier}': {e}"
                    )
                    raise

            # Perform the actual reply while holding the lock
            try:
                result = await super().reply(
                    msg=msg,
                    structured_model=structured_model,
                )
                return result
            finally:
                # Restore original model if we swapped it
                if original_model is not None:
                    self.model = original_model
                    self.formatter = original_formatter
