# -*- coding: utf-8 -*-
"""Central plugin registry."""

from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProviderRegistration:
    """Provider registration record."""

    plugin_id: str
    provider_id: str
    provider_class: Type
    label: str
    base_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookRegistration:
    """Hook registration record."""

    plugin_id: str
    hook_name: str
    callback: Callable
    priority: int = 100


@dataclass
class ControlCommandRegistration:
    """Control command registration record."""

    plugin_id: str
    handler: Any  # BaseControlCommandHandler
    priority_level: int = 10


class PluginRegistry:
    """Central plugin registry (Singleton).

    This registry manages all plugin registrations and provides
    a centralized way to access plugin capabilities.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Initialize _initialized first to avoid pylint error
        if not hasattr(self, "_initialized"):
            self._initialized = False

        if self._initialized:
            return

        self._providers: Dict[str, ProviderRegistration] = {}
        self._startup_hooks: List[HookRegistration] = []
        self._shutdown_hooks: List[HookRegistration] = []
        self._control_commands: List[ControlCommandRegistration] = []
        # plugin_id → { tool_name → component_name }
        self._js_tool_renderers: Dict[str, Dict[str, str]] = {}
        self._runtime_helpers = None

        self._initialized = True

    def register_provider(
        self,
        plugin_id: str,
        provider_id: str,
        provider_class: Type,
        label: str,
        base_url: str,
        metadata: Dict[str, Any],
    ):
        """Register a provider.

        Args:
            plugin_id: Plugin identifier
            provider_id: Provider identifier
            provider_class: Provider class
            label: Display label
            base_url: API base URL
            metadata: Additional metadata

        Raises:
            ValueError: If provider_id already registered
        """
        if provider_id in self._providers:
            existing = self._providers[provider_id]
            raise ValueError(
                f"Provider '{provider_id}' already registered "
                f"by plugin '{existing.plugin_id}'",
            )

        self._providers[provider_id] = ProviderRegistration(
            plugin_id=plugin_id,
            provider_id=provider_id,
            provider_class=provider_class,
            label=label,
            base_url=base_url,
            metadata=metadata,
        )
        logger.info(
            f"Registered provider '{provider_id}' from plugin '{plugin_id}'",
        )

    def get_provider(self, provider_id: str) -> Optional[ProviderRegistration]:
        """Get provider registration.

        Args:
            provider_id: Provider identifier

        Returns:
            ProviderRegistration or None if not found
        """
        return self._providers.get(provider_id)

    def get_all_providers(self) -> Dict[str, ProviderRegistration]:
        """Get all provider registrations.

        Returns:
            Dictionary of provider_id -> ProviderRegistration
        """
        return self._providers.copy()

    def set_runtime_helpers(self, helpers):
        """Set runtime helpers.

        Args:
            helpers: RuntimeHelpers instance
        """
        self._runtime_helpers = helpers

    def get_runtime_helpers(self):
        """Get runtime helpers.

        Returns:
            RuntimeHelpers instance or None
        """
        return self._runtime_helpers

    def register_startup_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a startup hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._startup_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._startup_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered startup hook '{hook_name}' from plugin '{plugin_id}' "
            f"(priority={priority})",
        )

    def register_shutdown_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a shutdown hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._shutdown_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._shutdown_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered shutdown hook '{hook_name}' from plugin "
            f"'{plugin_id}' (priority={priority})",
        )

    def get_startup_hooks(self) -> List[HookRegistration]:
        """Get all startup hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._startup_hooks.copy()

    def get_shutdown_hooks(self) -> List[HookRegistration]:
        """Get all shutdown hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._shutdown_hooks.copy()

    def register_control_command(
        self,
        plugin_id: str,
        handler: Any,
        priority_level: int = 10,
    ):
        """Register a control command handler.

        Args:
            plugin_id: Plugin identifier
            handler: Control command handler instance
            priority_level: Command priority (default: 10 = high)
        """
        cmd_reg = ControlCommandRegistration(
            plugin_id=plugin_id,
            handler=handler,
            priority_level=priority_level,
        )
        self._control_commands.append(cmd_reg)
        logger.info(
            f"Registered control command '{handler.command_name}' "
            f"from plugin '{plugin_id}' (priority={priority_level})",
        )

    def get_control_commands(self) -> List[ControlCommandRegistration]:
        """Get all registered control command handlers.

        Returns:
            List of ControlCommandRegistration
        """
        return self._control_commands.copy()

    def register_js_tool_renderer(
        self,
        plugin_id: str,
        tool_name: str,
        component_name: str,
    ):
        """Register a JS tool renderer mapping.

        Maps a backend tool name to a frontend JS component name exported
        by the plugin's UI module.

        Args:
            plugin_id: Plugin identifier
            tool_name: Backend tool name (e.g. "view_image")
            component_name: JS component name exported by the plugin
                (e.g. "ViewImageCard")
        """
        if plugin_id not in self._js_tool_renderers:
            self._js_tool_renderers[plugin_id] = {}

        self._js_tool_renderers[plugin_id][tool_name] = component_name
        logger.info(
            f"Registered JS tool renderer '{tool_name}' -> "
            f"'{component_name}' from plugin '{plugin_id}'",
        )

    def get_js_tool_renderers(
        self,
        plugin_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Get JS tool renderer mappings.

        Args:
            plugin_id: If provided, return only renderers for this plugin.
                Otherwise return all renderers merged (later plugins
                override earlier ones for the same tool name).

        Returns:
            Dictionary of tool_name -> component_name
        """
        if plugin_id is not None:
            return self._js_tool_renderers.get(plugin_id, {}).copy()

        merged: Dict[str, str] = {}
        for renderers in self._js_tool_renderers.values():
            merged.update(renderers)
        return merged

    # ── Unregister methods (for dynamic unloading) ───────────────────────

    def unregister_startup_hooks_by_plugin(self, plugin_id: str) -> int:
        """Remove all startup hooks registered by a specific plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Number of hooks removed
        """
        before = len(self._startup_hooks)
        self._startup_hooks = [
            h for h in self._startup_hooks if h.plugin_id != plugin_id
        ]
        removed = before - len(self._startup_hooks)
        if removed:
            logger.info(
                f"Unregistered {removed} startup hook(s) "
                f"from plugin '{plugin_id}'",
            )
        return removed

    def unregister_shutdown_hooks_by_plugin(self, plugin_id: str) -> int:
        """Remove all shutdown hooks registered by a specific plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Number of hooks removed
        """
        before = len(self._shutdown_hooks)
        self._shutdown_hooks = [
            h for h in self._shutdown_hooks if h.plugin_id != plugin_id
        ]
        removed = before - len(self._shutdown_hooks)
        if removed:
            logger.info(
                f"Unregistered {removed} shutdown hook(s) "
                f"from plugin '{plugin_id}'",
            )
        return removed

    def unregister_control_commands_by_plugin(self, plugin_id: str) -> int:
        """Remove all control commands registered by a specific plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Number of commands removed
        """
        before = len(self._control_commands)
        self._control_commands = [
            c for c in self._control_commands if c.plugin_id != plugin_id
        ]
        removed = before - len(self._control_commands)
        if removed:
            logger.info(
                f"Unregistered {removed} control command(s) "
                f"from plugin '{plugin_id}'",
            )
        return removed

    def unregister_js_tool_renderers_by_plugin(self, plugin_id: str) -> int:
        """Remove all JS tool renderer mappings registered by a plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Number of renderers removed
        """
        renderers = self._js_tool_renderers.pop(plugin_id, {})
        if renderers:
            logger.info(
                f"Unregistered {len(renderers)} JS tool renderer(s) "
                f"from plugin '{plugin_id}'",
            )
        return len(renderers)

    def unregister_all_by_plugin(self, plugin_id: str) -> Dict[str, int]:
        """Remove **all** registrations belonging to a specific plugin.

        This is the primary method used during dynamic plugin unloading.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Dictionary summarising how many items were removed per category
        """
        summary = {
            "startup_hooks": self.unregister_startup_hooks_by_plugin(
                plugin_id,
            ),
            "shutdown_hooks": self.unregister_shutdown_hooks_by_plugin(
                plugin_id,
            ),
            "control_commands": self.unregister_control_commands_by_plugin(
                plugin_id,
            ),
            "js_tool_renderers": self.unregister_js_tool_renderers_by_plugin(
                plugin_id,
            ),
        }
        total = sum(summary.values())
        if total:
            logger.info(
                f"Unregistered all resources from plugin '{plugin_id}': "
                f"{summary}",
            )
        return summary
