# -*- coding: utf-8 -*-
# pylint:disable=too-many-nested-blocks
"""Central plugin registry."""

from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass, field
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# Registered on the console SPA catch-all in ``_app.py`` so plugin HTTP
# routes can be inserted *before* it (routes appended later would lose).
_CONSOLE_SPA_CATCHALL_ROUTE_NAME = "qwenpaw_console_spa_catchall"


def _find_console_spa_route_index(app: Any) -> Optional[int]:
    """Return the index of the SPA ``/{full_path:path}`` route if present."""
    routes = getattr(app.router, "routes", None)
    if routes is None:
        return None
    for i, route in enumerate(routes):
        if getattr(route, "name", None) == _CONSOLE_SPA_CATCHALL_ROUTE_NAME:
            return i
    return None


def _mount_plugin_http_on_app(
    app: Any,
    router: APIRouter,
    *,
    full_path_prefix: str,
    tags: Optional[List[Any]],
) -> List[Any]:
    """Include *router* on *app* so it matches before the console SPA route."""
    routes = app.router.routes
    spa_idx = _find_console_spa_route_index(app)
    n_before = len(routes)
    app.include_router(router, prefix=full_path_prefix, tags=tags)
    added = routes[n_before:]
    del routes[n_before:]
    if spa_idx is not None:
        for route in reversed(added):
            routes.insert(spa_idx, route)
    else:
        routes.extend(added)
    # Invalidate the cached OpenAPI schema so the next /openapi.json
    # request reflects the newly added plugin routes. FastAPI caches
    # the schema on first access and never regenerates it otherwise.
    app.openapi_schema = None
    return list(added)


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


@dataclass
class HttpRouterRegistration:
    """HTTP routes contributed by a backend plugin under ``/api``."""

    plugin_id: str
    prefix: str
    routes: List[Any]


class PluginRegistry:  # pylint:disable=too-many-public-methods
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
        self._runtime_helpers = None
        self._plugin_manifests: Dict[str, Dict[str, Any]] = {}
        self._plugin_http_app: Optional[Any] = None
        self._http_router_registrations: List[HttpRouterRegistration] = []
        self._http_prefix_to_plugin: Dict[str, str] = {}

        self._initialized = True

    def set_plugin_http_app(self, app: Any) -> None:
        """Attach the FastAPI application used to mount plugin HTTP routes.

        Must be called once before any ``register_http_router`` (typically
        from application lifespan before ``load_all_plugins``).

        Args:
            app: The root ``FastAPI`` instance.
        """
        self._plugin_http_app = app

    def register_http_router(
        self,
        plugin_id: str,
        router: APIRouter,
        *,
        prefix: str,
        tags: Optional[List[Any]] = None,
    ) -> None:
        """Mount a plugin ``APIRouter`` at ``/api`` + *prefix*.

        Args:
            plugin_id: Owning plugin id
            router: Router defining plugin HTTP handlers
            prefix: URL prefix under ``/api``, e.g. ``/pets`` for
                ``GET /api/pets/...``. Must start with ``/`` and must not
                end with ``/`` (except the single slash ``/`` is not allowed).
            tags: Optional OpenAPI tags for included routes

        Raises:
            RuntimeError: If the FastAPI app was not configured.
            ValueError: On invalid *prefix* or duplicate prefix.
        """
        http_app = self._plugin_http_app
        if http_app is None:
            raise RuntimeError(
                "Cannot register plugin HTTP routes: FastAPI app was not "
                "configured (internal setup error).",
            )

        normalized = prefix.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        normalized = normalized.rstrip("/") or "/"
        if normalized == "/":
            raise ValueError(
                "Plugin HTTP prefix must not be '/' alone; use a path "
                "segment such as '/pets'.",
            )

        if normalized in self._http_prefix_to_plugin:
            owner = self._http_prefix_to_plugin[normalized]
            raise ValueError(
                f"Plugin HTTP prefix '{normalized}' is already registered "
                f"by plugin '{owner}'",
            )

        effective_tags: Optional[List[Any]]
        if tags is not None:
            effective_tags = list(tags)
        else:
            effective_tags = [f"plugin:{plugin_id}"]

        full_prefix = f"/api{normalized}"
        added = _mount_plugin_http_on_app(
            http_app,
            router,
            full_path_prefix=full_prefix,
            tags=effective_tags,
        )

        self._http_router_registrations.append(
            HttpRouterRegistration(
                plugin_id=plugin_id,
                prefix=normalized,
                routes=added,
            ),
        )
        self._http_prefix_to_plugin[normalized] = plugin_id
        logger.info(
            "Registered HTTP routes for plugin '%s' at prefix '/api%s'",
            plugin_id,
            normalized,
        )

    def get_http_router_registrations(self) -> List[HttpRouterRegistration]:
        """Return a copy of HTTP router registrations (for diagnostics)."""
        return list(self._http_router_registrations)

    def _unregister_plugin_http_routes(self, plugin_id: str) -> None:
        http_app = self._plugin_http_app
        if http_app is None:
            return

        to_drop = [
            reg
            for reg in self._http_router_registrations
            if reg.plugin_id == plugin_id
        ]
        routes = http_app.router.routes
        for reg in to_drop:
            self._http_prefix_to_plugin.pop(reg.prefix, None)
            for route in reg.routes:
                try:
                    routes.remove(route)
                except ValueError:
                    logger.warning(
                        "Could not remove plugin HTTP route %r for '%s' "
                        "(already removed?)",
                        getattr(route, "path", route),
                        plugin_id,
                    )

        self._http_router_registrations = [
            r
            for r in self._http_router_registrations
            if r.plugin_id != plugin_id
        ]

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

    def register_plugin_manifest(
        self,
        plugin_id: str,
        manifest: Dict[str, Any],
    ):
        """Register plugin manifest.

        Args:
            plugin_id: Plugin identifier
            manifest: Plugin manifest dictionary
        """
        self._plugin_manifests[plugin_id] = manifest
        logger.debug(f"Registered manifest for plugin '{plugin_id}'")

    def get_all_plugin_manifests(self) -> Dict[str, Dict[str, Any]]:
        """Get all plugin manifests.

        Returns:
            Dictionary of plugin_id -> manifest
        """
        return self._plugin_manifests.copy()

    def get_plugin_manifest(
        self,
        plugin_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get plugin manifest.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin manifest dict or None
        """
        return self._plugin_manifests.get(plugin_id)

    def unregister_plugin(self, plugin_id: str) -> None:
        """Remove all in-memory registrations for a plugin.

        Clears manifest, providers, hooks, and control commands
        that were registered under the given plugin_id.  Does not
        touch disk or agent configurations.

        Args:
            plugin_id: Plugin identifier to remove
        """
        self._unregister_plugin_http_routes(plugin_id)

        self._plugin_manifests.pop(plugin_id, None)

        providers_to_remove = [
            pid
            for pid, reg in self._providers.items()
            if reg.plugin_id == plugin_id
        ]
        for pid in providers_to_remove:
            del self._providers[pid]
            logger.info(
                f"Unregistered provider '{pid}' " f"for plugin '{plugin_id}'",
            )

        self._startup_hooks = [
            h for h in self._startup_hooks if h.plugin_id != plugin_id
        ]
        self._shutdown_hooks = [
            h for h in self._shutdown_hooks if h.plugin_id != plugin_id
        ]
        self._control_commands = [
            c for c in self._control_commands if c.plugin_id != plugin_id
        ]
        logger.info(
            f"Unregistered all entries for plugin '{plugin_id}'",
        )

    def get_plugin_id_for_tool(self, tool_name: str) -> Optional[str]:
        """Get plugin ID that provides a specific tool.

        Args:
            tool_name: Tool function name

        Returns:
            Plugin ID or None
        """
        for plugin_id, manifest in self._plugin_manifests.items():
            meta = manifest.get("meta", {})
            # Check old format: meta.tool_name
            if meta.get("tool_name") == tool_name:
                return plugin_id
            # Check new format: meta.tools array
            tools = meta.get("tools", [])
            if isinstance(tools, list):
                for tool in tools:
                    if (
                        isinstance(tool, dict)
                        and tool.get("name") == tool_name
                    ):
                        return plugin_id
        return None

    def get_tool_config(
        self,
        tool_name: str,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get tool configuration for a specific agent.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier

        Returns:
            Tool configuration dict or None
        """
        try:
            from ..config.config import load_agent_config

            agent_config = load_agent_config(agent_id)
            if (
                not agent_config.tools
                or tool_name not in agent_config.tools.builtin_tools
            ):
                return None

            tool_config = agent_config.tools.builtin_tools[tool_name]
            return tool_config.config if tool_config.config else None
        except Exception as e:
            logger.error(f"Failed to load tool config: {e}")
            return None

    def set_tool_config(
        self,
        tool_name: str,
        agent_id: str,
        config: Dict[str, Any],
    ) -> None:
        """Save tool configuration for a specific agent.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier
            config: Configuration data
        """
        try:
            from ..config.config import (
                load_agent_config,
                save_agent_config,
            )

            agent_config = load_agent_config(agent_id)
            if (
                not agent_config.tools
                or tool_name not in agent_config.tools.builtin_tools
            ):
                raise ValueError(f"Tool '{tool_name}' not found in agent")

            # Update tool config
            agent_config.tools.builtin_tools[tool_name].config = config

            # Save agent config
            save_agent_config(agent_id, agent_config)

            logger.info(
                f"Saved config for tool '{tool_name}' in agent '{agent_id}'",
            )
        except Exception as e:
            logger.error(f"Failed to save tool config: {e}")
            raise
