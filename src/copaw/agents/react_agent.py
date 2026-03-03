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
from agentscope.message import Msg
from agentscope.tool import Toolkit
from pydantic import BaseModel

from .command_handler import CommandHandler
from .hooks import BootstrapHook, MemoryCompactionHook
from .memory import CoPawInMemoryMemory
from .model_factory import create_model_and_formatter
from .prompt import build_system_prompt_from_working_dir
from .skills_manager import (
    ensure_skills_initialized,
    get_working_skills_dir,
    list_available_skills,
)
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

logger = logging.getLogger(__name__)


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
        max_iters: int = 50,
        max_input_length: int = 128 * 1024,  # 128K = 131072 tokens
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
        """
        self._env_context = env_context
        self._max_input_length = max_input_length
        self._mcp_clients = mcp_clients or []

        # Track dynamically connected MCP clients (from skills like dynamic-mcp)
        self._dynamic_mcp_clients: dict = {}

        # Session-scoped dynamic MCP connection params (persisted via register_state)
        self._dynamic_mcp_connection_params: list = []

        # Memory compaction threshold: configurable ratio of max_input_length
        self._memory_compact_threshold = int(
            max_input_length * MEMORY_COMPACT_RATIO,
        )

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit()

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

        # Register dynamic MCP connection params as session state
        # so they persist across agent recreations within the same session
        self.register_state("_dynamic_mcp_connection_params")

        # Setup memory manager
        self._setup_memory_manager(
            enable_memory_manager,
            memory_manager,
        )

        # Setup command handler
        self.command_handler = CommandHandler(
            agent_name=self.name,
            memory=self.memory,
            formatter=self.formatter,
            memory_manager=self.memory_manager,
            enable_memory_manager=self._enable_memory_manager,
        )

        # Register hooks
        self._register_hooks()

    def _create_toolkit(self) -> Toolkit:
        """Create and populate toolkit with built-in tools.

        Returns:
            Configured toolkit instance
        """
        toolkit = Toolkit()

        # Register built-in tools
        toolkit.register_tool_function(execute_shell_command)
        toolkit.register_tool_function(read_file)
        toolkit.register_tool_function(write_file)
        toolkit.register_tool_function(edit_file)
        toolkit.register_tool_function(browser_use)
        toolkit.register_tool_function(desktop_screenshot)
        toolkit.register_tool_function(send_file_to_user)
        toolkit.register_tool_function(get_current_time)

        return toolkit

    def _register_skills(self, toolkit: Toolkit) -> None:
        """Load and register skills from working directory.

        This method performs two registrations:
        1. Register agent skill description (adds to system prompt)
        2. Dynamically load tools from skill's tools.py if available

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
                    # Step 1: Register agent skill (adds skill description to prompt)
                    toolkit.register_agent_skill(str(skill_dir))
                    logger.debug("Registered agent skill: %s", skill_name)
                    
                    # Step 2: Dynamically load tools from tools.py if present
                    tools_py = skill_dir / "tools.py"
                    if tools_py.exists():
                        try:
                            import importlib.util
                            
                            # Create a unique module name to avoid conflicts
                            module_name = f"copaw_skill_{skill_name}_tools"
                            spec = importlib.util.spec_from_file_location(
                                module_name, 
                                str(tools_py)
                            )
                            
                            if spec is None or spec.loader is None:
                                logger.warning(
                                    "Could not create module spec for tools.py in skill '%s'",
                                    skill_name,
                                )
                                continue
                                
                            tools_module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(tools_module)
                            
                            # Check for get_tools function
                            if hasattr(tools_module, 'get_tools'):
                                # Call get_tools to retrieve tool functions
                                # Note: get_tools signature is (agent, session_service, app_info)
                                new_tools = tools_module.get_tools(
                                    agent=self,
                                    session_service=None,
                                    app_info=None
                                )
                                
                                # Register each tool to toolkit
                                for tool_func in new_tools:
                                    toolkit.register_tool_function(tool_func)
                                    tool_name = getattr(tool_func, '__name__', str(tool_func))
                                    logger.debug(
                                        "Registered tool from skill '%s': %s",
                                        skill_name,
                                        tool_name,
                                    )
                            else:
                                logger.debug(
                                    "Skill '%s' tools.py has no get_tools function; skipping tool registration",
                                    skill_name,
                                )
                                
                        except Exception as e:
                            logger.warning(
                                "Failed to load tools from skill '%s': %s",
                                skill_name,
                                e,
                            )
                            
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
    ) -> None:
        """Setup memory manager and register memory search tool if enabled.

        Args:
            enable_memory_manager: Whether to enable memory manager
            memory_manager: Optional memory manager instance
        """
        # Check env var: if ENABLE_MEMORY_MANAGER=false, disable memory manager
        env_enable_mm = os.getenv("ENABLE_MEMORY_MANAGER", "")
        if env_enable_mm.lower() == "false":
            enable_memory_manager = False

        self._enable_memory_manager: bool = enable_memory_manager
        self.memory_manager = memory_manager

        # Register memory_search tool if enabled and available
        if self._enable_memory_manager and self.memory_manager is not None:
            self.memory_manager.chat_model = self.model
            self.memory_manager.formatter = self.formatter

            memory_search_tool = create_memory_search_tool(self.memory_manager)
            self.toolkit.register_tool_function(memory_search_tool)
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

    async def register_mcp_clients(self) -> None:
        """Register MCP clients on this agent's toolkit after construction."""
        for client in self._mcp_clients:
            await self.toolkit.register_mcp_client(client)

    async def restore_dynamic_mcp_connections(self) -> int:
        """Restore dynamic MCP connections from session state.

        Called after load_session_state to re-establish MCP connections
        that were created by connect_mcp in previous turns of this session.

        Returns:
            Number of successfully restored connections.
        """
        if not self._dynamic_mcp_connection_params:
            return 0

        restored = 0
        failed_indices = []

        for idx, conn in enumerate(self._dynamic_mcp_connection_params):
            client_id = conn.get("client_id", "")
            if client_id in self._dynamic_mcp_clients:
                restored += 1
                continue

            mode = conn.get("mode")
            mcp_client = None

            try:
                if mode == "remote":
                    mcp_client = HttpStatefulClient(
                        name=conn["client_name"],
                        transport=conn["transport"],
                        url=conn["source"],
                        headers=conn.get("headers", {}),
                        timeout=15,
                    )
                elif mode == "local":
                    import os as _os
                    final_env = _os.environ.copy()
                    final_env.update(conn.get("env_vars", {}))
                    mcp_client = StdIOStatefulClient(
                        name=conn["client_name"],
                        command=conn["source"],
                        args=conn.get("args", []),
                        env=final_env,
                    )
                else:
                    failed_indices.append(idx)
                    continue

                await asyncio.wait_for(mcp_client.connect(), timeout=15)
                await self.toolkit.register_mcp_client(
                    mcp_client,
                    namesake_strategy="skip",
                )
                self._dynamic_mcp_clients[client_id] = mcp_client
                restored += 1
                logger.info(
                    "[DynamicMCP] Restored connection: %s",
                    client_id,
                )

            except Exception as e:
                logger.warning(
                    "[DynamicMCP] Failed to restore %s: %s",
                    client_id,
                    e,
                )
                failed_indices.append(idx)
                if mcp_client and getattr(mcp_client, "is_connected", False):
                    try:
                        await mcp_client.close()
                    except Exception:
                        pass

        # Remove failed connections from session state
        if failed_indices:
            self._dynamic_mcp_connection_params = [
                c for i, c in enumerate(self._dynamic_mcp_connection_params)
                if i not in failed_indices
            ]

        if restored > 0:
            logger.info(
                "[DynamicMCP] Restored %d dynamic MCP connection(s)",
                restored,
            )

        return restored

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
