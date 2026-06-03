# -*- coding: utf-8 -*-
"""Plugin API for plugin developers."""

from typing import Any, Callable, Dict, Type
import logging

logger = logging.getLogger(__name__)


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

    def register_tool(
        self,
        tool_name: str,
        tool_func: Callable,
        *,
        description: str = "",
        icon: str = "🧩",
        enabled: bool = False,
        async_execution: bool = False,
    ) -> None:
        """Register a tool function for agent use.

        This provides a first-class plugin API for tool plugins instead of
        requiring each plugin to hand-roll importlib loading, setattr
        injection, and agent-config mutation logic.
        """
        import qwenpaw.agents.tools as tools_module
        from qwenpaw.app.agent_context import get_current_agent_id
        from qwenpaw.config.config import (
            BuiltinToolConfig,
            ToolsConfig,
            load_agent_config,
            save_agent_config,
        )

        setattr(tools_module, tool_name, tool_func)
        if tool_name not in tools_module.__all__:
            tools_module.__all__.append(tool_name)

        try:
            agent_id = get_current_agent_id()
            if not agent_id:
                logger.warning(
                    "No current agent ID found while registering tool '%s'",
                    tool_name,
                )
                return

            agent_config = load_agent_config(agent_id)
            if not agent_config.tools:
                agent_config.tools = ToolsConfig()

            if tool_name not in agent_config.tools.builtin_tools:
                agent_config.tools.builtin_tools[
                    tool_name
                ] = BuiltinToolConfig(
                    name=tool_name,
                    enabled=enabled,
                    description=(
                        f"{icon} {description}" if description else ""
                    ),
                    async_execution=async_execution,
                )
                save_agent_config(agent_id, agent_config)
                logger.info(
                    "Plugin '%s' registered tool '%s' for agent %s",
                    self.plugin_id,
                    tool_name,
                    agent_id,
                )
            else:
                logger.info(
                    "Tool '%s' already exists in agent %s",
                    tool_name,
                    agent_id,
                )
        except Exception as e:
            logger.error(
                "Failed to persist tool '%s' config for plugin '%s': %s",
                tool_name,
                self.plugin_id,
                e,
                exc_info=True,
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
