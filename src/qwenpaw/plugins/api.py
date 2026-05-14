# -*- coding: utf-8 -*-
"""Plugin API for plugin developers."""

import logging
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


def get_tool_config(tool_name: str) -> Optional[Dict[str, Any]]:
    """Get tool configuration for the currently active agent.

    Convenience helper for tool plugin developers. Call this inside
    tool functions to retrieve user-configured values (api_key,
    endpoint, timeout, etc.) without needing a PluginApi reference.

    Args:
        tool_name: The registered name of the tool function.

    Returns:
        Configuration dict or None if the tool is not configured.

    Example:
        >>> from qwenpaw.plugins import get_tool_config
        >>> config = get_tool_config("my_tool")
        >>> if not config:
        ...     return ToolResponse(...)  # not configured
        >>> api_key = config.get("api_key")
    """
    try:
        from .registry import PluginRegistry
        from ..app.agent_context import get_current_agent_id

        agent_id = get_current_agent_id()
        if not agent_id:
            logger.warning(
                "get_tool_config: no current agent ID found",
            )
            return None

        registry = PluginRegistry()
        return registry.get_tool_config(tool_name, agent_id)
    except Exception as e:
        logger.error(f"get_tool_config failed for {tool_name}: {e}")
        return None


class PluginApi:
    """Plugin API - Interface for plugin developers.

    This class provides the API that plugins use to register their
    capabilities.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        manifest: Dict[str, Any] = None,
    ):
        """Initialize plugin API.

        Args:
            plugin_id: Unique plugin identifier
            config: Plugin configuration dictionary
            manifest: Plugin manifest dictionary (from plugin.json)
        """
        self.plugin_id = plugin_id
        self.config = config
        self.manifest = manifest or {}
        self._registry = None

    def set_registry(self, registry):
        """Set registry reference (called by loader).

        Args:
            registry: PluginRegistry instance
        """
        self._registry = registry

    def register_provider(
        self,
        provider_id: str,
        provider_class: Type,
        label: str = "",
        base_url: str = "",
        **metadata,
    ):
        """Register a custom LLM Provider.

        Args:
            provider_id: Unique provider identifier
            provider_class: Provider class (inherits from BaseProvider)
            label: Display name for the provider
            base_url: API base URL
            **metadata: Additional metadata (chat_model, require_api_key, etc.)

        Example:
            >>> api.register_provider(
            ...     provider_id="my-provider",
            ...     provider_class=MyProvider,
            ...     label="My Custom Provider",
            ...     base_url="https://api.example.com/v1",
            ...     chat_model="OpenAIChatModel",
            ...     require_api_key=True,
            ... )
        """
        if self._registry:
            # Merge plugin manifest meta with provider metadata
            merged_metadata = dict(metadata)
            if "meta" in self.manifest:
                merged_metadata["meta"] = self.manifest["meta"]

            self._registry.register_provider(
                plugin_id=self.plugin_id,
                provider_id=provider_id,
                provider_class=provider_class,
                label=label or provider_id,
                base_url=base_url,
                metadata=merged_metadata,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered provider "
                f"'{provider_id}'",
            )

    def register_startup_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a startup hook.

        Args:
            hook_name: Unique hook identifier
            callback: Async or sync function to call on startup
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_startup_hook(
            ...     hook_name="init_sdk",
            ...     callback=self.on_startup,
            ...     priority=0,  # Execute first
            ... )
        """
        if self._registry:
            self._registry.register_startup_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered startup hook "
                f"'{hook_name}' (priority={priority})",
            )

    def register_shutdown_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a shutdown hook.

        Args:
            hook_name: Unique hook identifier
            callback: Async or sync function to call on shutdown
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_shutdown_hook(
            ...     hook_name="cleanup_sdk",
            ...     callback=self.on_shutdown,
            ...     priority=100,
            ... )
        """
        if self._registry:
            self._registry.register_shutdown_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered shutdown hook "
                f"'{hook_name}' (priority={priority})",
            )

    def register_http_router(
        self,
        router: Any,
        *,
        prefix: str,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Expose REST endpoints under ``/api`` + *prefix*.

        Use a FastAPI ``APIRouter`` with route decorators such as
        ``@router.get("/")`` so that with ``prefix="/pets"`` the handler
        is served at ``GET /api/pets/`` (trailing slash follows FastAPI
        defaults for the mounted path).

        Args:
            router: ``fastapi.APIRouter`` instance
            prefix: Path under ``/api``, e.g. ``"/pets"``
            tags: Optional OpenAPI tags for these routes

        Raises:
            RuntimeError: If the registry has no HTTP parent router.
            ValueError: If *prefix* is invalid or already taken.
        """
        if self._registry:
            self._registry.register_http_router(
                self.plugin_id,
                router,
                prefix=prefix,
                tags=tags,
            )

    def register_control_command(
        self,
        handler: Any,
        priority_level: int = 10,
    ):
        """Register a control command handler.

        Args:
            handler: Control command handler instance
                (BaseControlCommandHandler)
            priority_level: Command priority (default: 10 = high)
        """
        if self._registry:
            self._registry.register_control_command(
                plugin_id=self.plugin_id,
                handler=handler,
                priority_level=priority_level,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered control command "
                f"'{handler.command_name}' (priority={priority_level})",
            )

    @property
    def runtime(self):
        """Access runtime helper functions.

        Returns:
            RuntimeHelpers instance or None
        """
        if self._registry:
            return self._registry.get_runtime_helpers()
        return None

    def get_tool_config(self, tool_name: str, agent_id: str) -> dict:
        """Get tool configuration from registry.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier

        Returns:
            Tool configuration dictionary (empty if not configured)
        """
        if self._registry:
            config = self._registry.get_tool_config(tool_name, agent_id)
            return config if config else {}
        return {}

    def set_tool_config(
        self,
        tool_name: str,
        agent_id: str,
        config: dict,
    ) -> None:
        """Save tool configuration to registry.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier
            config: Configuration dictionary
        """
        if self._registry:
            self._registry.set_tool_config(tool_name, agent_id, config)

    def register_tool(
        self,
        tool_name: str,
        tool_func: Callable,
        description: str = "",
        icon: str = "🔧",
        enabled: bool = False,
    ) -> None:
        """Register a tool function into the Agent's toolkit.

        This is the recommended way for tool plugins to register tools.
        It handles all registration boilerplate:
        - Adds the function to ``qwenpaw.agents.tools`` module
        - Appends the name to ``tools.__all__``
        - Creates a ``BuiltinToolConfig`` entry in the current agent
          config (disabled by default so the user can opt-in)

        The actual registration is deferred to a startup hook so it
        runs after the application and agent context are fully
        initialized.

        Args:
            tool_name: Unique name for the tool function.
                Must match the function name used in the agent prompt.
            tool_func: The async (or sync) tool callable to register.
            description: Human-readable description shown in the UI.
            icon: Display icon (emoji string). Default: "🔧".
            enabled: Whether the tool is enabled by default. The
                recommended value is False so the user explicitly
                enables the tool. Default: False.

        Example:
            >>> from .tool import my_tool_func
            >>> def register(self, api: PluginApi):
            ...     api.register_tool(
            ...         tool_name="my_tool",
            ...         tool_func=my_tool_func,
            ...         description="Does something useful",
            ...         icon="🔧",
            ...     )
        """

        def _startup_register():
            try:
                import qwenpaw.agents.tools as tools_module

                setattr(tools_module, tool_name, tool_func)
                if tool_name not in tools_module.__all__:
                    tools_module.__all__.append(tool_name)
                logger.info(
                    f"Registered tool function '{tool_name}' "
                    f"to tools module",
                )

                from ..config.config import (
                    BuiltinToolConfig,
                    load_agent_config,
                    save_agent_config,
                )
                from ..app.agent_context import get_current_agent_id

                agent_id = get_current_agent_id()
                if not agent_id:
                    logger.warning(
                        f"No current agent ID; tool '{tool_name}' "
                        f"will be available after restart",
                    )
                    return

                agent_config = load_agent_config(agent_id)

                if not agent_config.tools:
                    from ..config.config import ToolsConfig

                    agent_config.tools = ToolsConfig()

                if tool_name not in agent_config.tools.builtin_tools:
                    agent_config.tools.builtin_tools[
                        tool_name
                    ] = BuiltinToolConfig(
                        name=tool_name,
                        enabled=enabled,
                        description=description,
                        display_to_user=True,
                        async_execution=False,
                        icon=icon,
                    )
                    logger.info(
                        f"Added tool '{tool_name}' to agent "
                        f"'{agent_id}' config (enabled={enabled})",
                    )
                else:
                    logger.info(
                        f"Tool '{tool_name}' already in agent "
                        f"'{agent_id}' config, skipping",
                    )

                save_agent_config(agent_id, agent_config)

            except Exception as exc:
                logger.error(
                    f"Failed to register tool '{tool_name}': {exc}",
                    exc_info=True,
                )

        self.register_startup_hook(
            hook_name=f"register_tool_{self.plugin_id}_{tool_name}",
            callback=_startup_register,
            priority=50,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled tool "
            f"'{tool_name}' for registration on startup",
        )
