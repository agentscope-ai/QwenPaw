# -*- coding: utf-8 -*-
"""Plugin API for plugin developers."""

from typing import Any, Callable, Dict, List, Type
import logging

logger = logging.getLogger(__name__)

class PluginApi:
    """Plugin API - Interface for plugin developers.

    This class provides the API that plugins use to register their
    capabilities.  It also tracks every registration so that
    ``unregister_all()`` can cleanly remove them during dynamic
    unloading.
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

        # Track registered resources for unregister_all()
        self._registered_startup_hooks: List[str] = []
        self._registered_shutdown_hooks: List[str] = []
        self._registered_js_tool_renderers: List[str] = []
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
            self._registered_startup_hooks.append(hook_name)
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
            self._registered_shutdown_hooks.append(hook_name)
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

    def register_js_tool_renderer(
        self,
        tool_name: str,
        component_name: str,
    ):
        """Register a JS tool renderer mapping.

        Declares that the frontend JS component ``component_name``
        (exported by this plugin's UI module) should be used to render
        the output of the backend tool ``tool_name``.

        Args:
            tool_name: Backend tool name (e.g. "view_image")
            component_name: JS component name exported by the plugin's
                UI module (e.g. "ViewImageCard")

        Example:
            >>> api.register_js_tool_renderer("view_image", "ViewImageCard")
        """
        if self._registry:
            self._registry.register_js_tool_renderer(
                plugin_id=self.plugin_id,
                tool_name=tool_name,
                component_name=component_name,
            )
            self._registered_js_tool_renderers.append(tool_name)
            logger.info(
                f"Plugin '{self.plugin_id}' registered JS tool renderer "
                f"'{tool_name}' -> '{component_name}'",
            )

    def unregister_all(self) -> None:
        """Remove all registrations made by this plugin.

        Delegates to ``PluginRegistry.unregister_all_by_plugin`` which
        handles every category in one call.  This is the primary method
        used during dynamic plugin unloading.
        """
        if self._registry:
            summary = self._registry.unregister_all_by_plugin(self.plugin_id)
            logger.info(
                f"Plugin '{self.plugin_id}' unregistered all resources: "
                f"{summary}",
            )

        # Clear local tracking lists
        self._registered_startup_hooks.clear()
        self._registered_shutdown_hooks.clear()
        self._registered_js_tool_renderers.clear()

    @property
    def runtime(self):
        """Access runtime helper functions.

        Returns:
            RuntimeHelpers instance or None
        """
        if self._registry:
            return self._registry.get_runtime_helpers()
        return None
