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
    reload_safe: bool = False


@dataclass
class ControlCommandRegistration:
    """Control command registration record."""

    plugin_id: str
    handler: Any  # BaseControlCommandHandler
    priority_level: int = 10


@dataclass
class MiddlewareRegistration:
    """Middleware factory registration record."""

    plugin_id: str
    factory: Callable
    priority: int = 100


@dataclass
class ChannelRegistration:
    """Channel registration record from a plugin."""

    plugin_id: str
    channel_key: str
    channel_class: Type
    label: str = ""
    description: str = ""
    config_fields: List[Dict[str, Any]] = field(default_factory=list)
    icon: str = ""
    doc_url: Any = ""


@dataclass
class HttpRouterRegistration:
    """HTTP routes contributed by a backend plugin under ``/api``."""

    plugin_id: str
    prefix: str
    routes: List[Any]


@dataclass
class PromptSectionRegistration:
    """System-prompt section contributed by a plugin."""

    plugin_id: str
    name: str
    after: str
    agent_id: Optional[str]
    provider: Callable[[Any], str]


@dataclass(frozen=True)
class PawAppLocalToolRegistration:
    """Private callable owned by exactly one PawApp runtime."""

    plugin_id: str
    name: str
    func: Callable
    description: str = ""
    input_schema: Optional[Dict[str, Any]] = None
    is_read_only: bool = False


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
        self._uninstall_hooks: List[HookRegistration] = []
        self._workspace_created_hooks: List[HookRegistration] = []
        self._control_commands: List[ControlCommandRegistration] = []
        self._channels: Dict[str, ChannelRegistration] = {}
        self._runtime_helpers = None
        self._plugin_manifests: Dict[str, Dict[str, Any]] = {}
        self._middleware_registrations: List[MiddlewareRegistration] = []
        self._plugin_http_app: Optional[Any] = None
        self._http_router_registrations: List[HttpRouterRegistration] = []
        self._http_prefix_to_plugin: Dict[str, str] = {}
        self._prompt_sections: List[PromptSectionRegistration] = []
        self._prompt_section_names: set = set()
        self._workspace_manager: Optional[Any] = None
        self._task_actions: Dict[tuple, Any] = {}
        self._pawapp_setup_checks: Dict[tuple[str, str], Any] = {}
        self._pawapp_setup_entries: Dict[tuple[str, str], Any] = {}
        self._pawapp_host_tools: Dict[str, frozenset[str]] = {}
        self._pawapp_host_skills: Dict[str, Dict[str, tuple[str, ...]]] = {}
        self._pawapp_local_tools: Dict[
            tuple[str, str],
            PawAppLocalToolRegistration,
        ] = {}
        self._pawapp_local_skill_dirs: Dict[str, List[Any]] = {}

        self._initialized = True

    def register_middleware(
        self,
        plugin_id: str,
        factory: Callable,
        priority: int = 100,
    ) -> None:
        """Register a middleware factory.

        The factory is invoked per request during agent assembly:
        ``factory(ctx, agent_config) -> MiddlewareBase | None``.

        Args:
            plugin_id: Plugin identifier
            factory: Callable returning a MiddlewareBase or None
            priority: Ordering priority (lower = outermost in onion model)
        """
        self._middleware_registrations.append(
            MiddlewareRegistration(
                plugin_id=plugin_id,
                factory=factory,
                priority=priority,
            ),
        )
        self._middleware_registrations.sort(key=lambda r: r.priority)
        logger.info(
            "Registered middleware factory from plugin '%s' (priority=%d)",
            plugin_id,
            priority,
        )

    def get_middleware_factories(self) -> List[MiddlewareRegistration]:
        """Get all middleware factory registrations sorted by priority.

        Returns:
            List of MiddlewareRegistration
        """
        return self._middleware_registrations.copy()

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

    def set_workspace_manager(self, manager) -> None:
        """Set the workspace manager reference.

        Called once during app lifespan startup so plugins can
        access workspace instances for registration.

        Args:
            manager: MultiAgentManager / WorkspaceRegistry instance
        """
        self._workspace_manager = manager

    def get_workspace_manager(self):
        """Get the workspace manager.

        Returns:
            MultiAgentManager instance or None
        """
        return self._workspace_manager

    @classmethod
    def get_stop_handlers(
        cls,
        agent_id: "str | None" = None,
    ) -> list:
        """Collect stop handlers.

        Args:
            agent_id: If provided, only return handlers
                registered on that workspace. Otherwise
                return handlers from all workspaces.

        Returns:
            List of StopHandlerRegistration objects.
        """
        inst = cls._instance
        if inst is None:
            return []
        mgr = inst.get_workspace_manager()
        if mgr is None:
            return []
        workspaces = getattr(
            mgr,
            "agents",
            getattr(mgr, "workspaces", {}),
        )
        if agent_id is not None:
            ws = workspaces.get(agent_id)
            if ws is None:
                return []
            plugins = getattr(ws, "plugins", None)
            if plugins is None:
                return []
            return list(
                getattr(plugins, "stop_handlers", []),
            )
        handlers: list = []
        for ws in workspaces.values():
            plugins = getattr(ws, "plugins", None)
            if plugins is None:
                continue
            ws_handlers = getattr(
                plugins,
                "stop_handlers",
                [],
            )
            handlers.extend(ws_handlers)
        return handlers

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

    def register_uninstall_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register an uninstall hook.

        Unlike shutdown hooks (which run on every app shutdown),
        uninstall hooks run only when a plugin is explicitly unloaded
        or removed.  Use these for cleanup that should happen once on
        uninstall — e.g. removing workspace skills, clearing manifest
        entries, or undoing monkey-patches.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function (sync or async).
                Receives keyword arguments:
                ``plugin_id``, ``delete_files`` (bool).
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._uninstall_hooks.append(hook)
        self._uninstall_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered uninstall hook '{hook_name}' from plugin "
            f"'{plugin_id}' (priority={priority})",
        )

    def get_uninstall_hooks(self) -> List[HookRegistration]:
        """Get all uninstall hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._uninstall_hooks.copy()

    def register_workspace_created_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
        reload_safe: bool = False,
    ):
        """Register a hook that fires when a new workspace is created.

        The callback receives a single ``workspace_info`` dict with at
        least ``agent_id`` and ``workspace_dir`` keys.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Sync or async callback function.
                Signature: ``(workspace_info: dict) -> None``
            priority: Priority (lower = earlier execution)
            reload_safe: Whether the callback only restores in-memory state
                and may run for a replacement workspace during reload. Such
                callbacks must not perform workspace filesystem provisioning.
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
            reload_safe=reload_safe,
        )
        self._workspace_created_hooks.append(hook)
        self._workspace_created_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered workspace_created hook '{hook_name}' from plugin "
            f"'{plugin_id}' (priority={priority})",
        )

    def get_workspace_created_hooks(self) -> List[HookRegistration]:
        """Get all workspace-created hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._workspace_created_hooks.copy()

    def get_workspace_setup_hooks(self) -> List[HookRegistration]:
        """Get in-memory workspace setup hooks sorted by priority."""
        return [
            hook for hook in self._workspace_created_hooks if hook.reload_safe
        ]

    def remove_hooks_by_name(
        self,
        plugin_id: str,
        hook_names: List[str],
    ) -> None:
        """Remove specific hooks registered by a plugin.

        Removes hooks matching the given ``hook_names`` from all hook
        lists (startup, shutdown, uninstall, workspace_created).

        Args:
            plugin_id: Plugin identifier that owns the hooks.
            hook_names: Hook names to remove.
        """
        names_set = set(hook_names)

        def _filter(hooks: list) -> list:
            return [
                h
                for h in hooks
                if not (h.plugin_id == plugin_id and h.hook_name in names_set)
            ]

        self._startup_hooks = _filter(self._startup_hooks)
        self._shutdown_hooks = _filter(self._shutdown_hooks)
        self._uninstall_hooks = _filter(self._uninstall_hooks)
        self._workspace_created_hooks = _filter(
            self._workspace_created_hooks,
        )
        logger.info(
            f"Removed hooks {hook_names} for plugin '{plugin_id}'",
        )

    def register_prompt_section(
        self,
        plugin_id: str,
        name: str,
        after: str,
        agent_id: Optional[str],
        provider: Callable[[Any], str],
    ) -> None:
        """Register a plugin-contributed system prompt section.

        Args:
            plugin_id: Owning plugin identifier.
            name: Unique section name.
            after: Host anchor this section follows.
            agent_id: Optional agent id filter; ``None`` applies globally.
            provider: Callable receiving the agent and returning text.

        Raises:
            ValueError: If *name* is already registered or *after* is not
                a valid host prompt anchor.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Prompt section name must not be empty")
        if normalized_name in self._prompt_section_names:
            raise ValueError(
                f"Prompt section '{normalized_name}' is already registered",
            )
        normalized_after = after.strip() or "workspace"
        from ..agents.prompt_builder import PromptBuilder

        if normalized_after not in PromptBuilder.HOST_ANCHORS:
            raise ValueError(
                f"Prompt section after='{after}' must reference a"
                " host anchor",
            )
        registration = PromptSectionRegistration(
            plugin_id=plugin_id,
            name=normalized_name,
            after=normalized_after,
            agent_id=agent_id,
            provider=provider,
        )
        self._prompt_sections.append(registration)
        self._prompt_section_names.add(normalized_name)
        logger.info(
            f"Registered prompt section '{normalized_name}' from plugin"
            f" '{plugin_id}' after '{normalized_after}'",
        )

    def get_prompt_sections(self) -> List[PromptSectionRegistration]:
        """Return a copy of registered prompt sections."""
        return list(self._prompt_sections)

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

    def register_channel(
        self,
        plugin_id: str,
        channel_key: str,
        channel_class: Type,
        label: str = "",
        description: str = "",
        config_fields: Optional[List[Dict[str, Any]]] = None,
        icon: str = "",
        doc_url: Any = "",
    ) -> None:
        """Register a custom channel from a plugin.

        Args:
            plugin_id: Owning plugin id.
            channel_key: Unique channel identifier (e.g. "slack").
            channel_class: Channel class (must be a BaseChannel subclass).
            label: Human-readable display name for the channel.
            description: Short description shown in the UI.
            config_fields: List of configuration field descriptors for
                the frontend form. Each dict should have at least
                ``name``, ``label``, ``type`` keys. Supported types:
                text, password, number, switch, select.
            icon: Optional display icon URL for the channel card. The
                frontend falls back to the default icon when it is empty
                or not a usable http(s) URL.
            doc_url: Optional documentation link for the channel. May be a
                plain http(s) URL string, or a localized mapping such as
                ``{"zh": "...", "en": "..."}``. The Console renders a "Doc"
                button only when it resolves to a usable http(s) URL.

        Raises:
            ValueError: If channel_key is already registered or invalid.
            TypeError: If channel_class is not a BaseChannel subclass.
        """
        from ..app.channels.base import BaseChannel
        from ..app.channels.registry import BUILTIN_CHANNEL_KEYS

        if not channel_key or not channel_key.strip():
            raise ValueError("channel_key must be a non-empty string")

        normalized_key = channel_key.strip().lower()

        if normalized_key != channel_key:
            logger.warning(
                "Channel key %r is not normalized (lowercase, no "
                "spaces); auto-normalizing to %r. Please update "
                "the channel class attribute to match.",
                channel_key,
                normalized_key,
            )
            setattr(channel_class, "channel", normalized_key)

        # Validate config_fields structure
        required_field_keys = {"name", "label", "type"}
        valid_field_types = {"text", "password", "number", "switch", "select"}
        for field_def in config_fields or []:
            missing = required_field_keys - field_def.keys()
            if missing:
                raise ValueError(
                    f"config_field missing required keys: {missing}",
                )
            if field_def["type"] not in valid_field_types:
                raise ValueError(
                    f"unsupported config_field type: {field_def['type']}; "
                    f"must be one of {valid_field_types}",
                )

        # Prevent overriding built-in channels
        if normalized_key in BUILTIN_CHANNEL_KEYS:
            raise ValueError(
                f"Channel '{normalized_key}' conflicts with a built-in "
                f"channel and cannot be registered by a plugin",
            )

        if normalized_key in self._channels:
            owner = self._channels[normalized_key].plugin_id
            raise ValueError(
                f"Channel '{normalized_key}' is already registered "
                f"by plugin '{owner}'",
            )

        if not (
            isinstance(channel_class, type)
            and issubclass(channel_class, BaseChannel)
            and channel_class is not BaseChannel
        ):
            raise TypeError(
                f"channel_class must be a concrete BaseChannel subclass, "
                f"got {channel_class!r}",
            )

        self._channels[normalized_key] = ChannelRegistration(
            plugin_id=plugin_id,
            channel_key=normalized_key,
            channel_class=channel_class,
            label=label or normalized_key,
            description=description,
            config_fields=config_fields or [],
            icon=(icon or "").strip(),
            doc_url=doc_url or "",
        )
        logger.info(
            f"Registered channel '{normalized_key}' from plugin "
            f"'{plugin_id}'",
        )

    def get_registered_channels(self) -> Dict[str, ChannelRegistration]:
        """Get all plugin-registered channels.

        Returns:
            Dictionary of channel_key -> ChannelRegistration.
        """
        return self._channels.copy()

    def get_channel_registration(
        self,
        channel_key: str,
    ) -> Optional[ChannelRegistration]:
        """Get a single channel registration by key.

        Args:
            channel_key: Channel identifier.

        Returns:
            ChannelRegistration or None.
        """
        return self._channels.get(channel_key)

    def _unregister_plugin_channels(self, plugin_id: str) -> None:
        """Remove all channels registered by a plugin (used on unload).

        Note: This only removes the registration from the registry.
        Already-instantiated channel instances in ChannelManager are
        cleaned up when the workspace triggers a config reload
        (schedule_agent_reload), which rebuilds the ChannelManager.
        """
        to_remove = [
            key
            for key, reg in self._channels.items()
            if reg.plugin_id == plugin_id
        ]
        for key in to_remove:
            del self._channels[key]
            logger.info(
                f"Unregistered channel '{key}' (plugin '{plugin_id}' "
                f"unloaded)",
            )

    def register_task_action(self, plugin_id: str, registration: Any) -> None:
        """Declare an action without starting or authorizing its runtime."""
        from qwenpaw.pawapp.tasks.binding import ActionRegistration

        if not isinstance(registration, ActionRegistration):
            raise ValueError("invalid task action registration")
        action = registration.action
        if action.app_id != plugin_id:
            raise ValueError("task action must belong to its plugin")
        key = (plugin_id, action.action_id)
        if key in self._task_actions:
            raise ValueError("task action already registered")
        missing = [
            requirement_id
            for requirement_id in registration.requirement_ids
            if (plugin_id, requirement_id) not in self._pawapp_setup_checks
        ]
        if missing:
            raise ValueError(
                "task action references unregistered setup requirements: "
                + ", ".join(missing),
            )
        for requirement_id in registration.requirement_ids:
            setup = self._pawapp_setup_checks[(plugin_id, requirement_id)]
            if action.action_id not in setup.requirement.required_for:
                raise ValueError(
                    "setup requirement does not declare this action",
                )
        # Freeze a serialized copy: plugin-side descriptor edits cannot change
        # the action after the Host has granted its digest.
        self._task_actions[key] = ActionRegistration(
            action=type(action).model_validate_json(action.model_dump_json()),
            factory=registration.factory,
            settings_entry=registration.settings_entry,
            requirement_ids=tuple(registration.requirement_ids),
        )

    def get_task_actions(self) -> Dict[tuple, Any]:
        return self._task_actions.copy()

    def register_pawapp_setup_check(
        self,
        plugin_id: str,
        registration: Any,
    ) -> None:
        """Register one App-owned, read-only readiness checker."""
        from qwenpaw.pawapp.setup import SetupCheckRegistration

        if not isinstance(registration, SetupCheckRegistration):
            raise ValueError("invalid PawApp setup check registration")
        requirement = registration.requirement
        key = (plugin_id, requirement.id)
        if key in self._pawapp_setup_checks:
            raise ValueError("PawApp setup requirement already registered")
        if (plugin_id, requirement.setup_entry_ref) not in (
            self._pawapp_setup_entries
        ):
            raise ValueError(
                "PawApp setup requirement entry is not registered",
            )
        frozen = type(requirement).model_validate_json(
            requirement.model_dump_json(),
        )
        self._pawapp_setup_checks[key] = SetupCheckRegistration(
            requirement=frozen,
            checker=registration.checker,
        )

    def get_pawapp_setup_checks(self) -> Dict[tuple[str, str], Any]:
        return self._pawapp_setup_checks.copy()

    def register_pawapp_setup_entry(
        self,
        plugin_id: str,
        registration: Any,
    ) -> None:
        """Register one App-owned presentation handler."""
        from qwenpaw.pawapp.setup import SetupEntryRegistration

        if not isinstance(registration, SetupEntryRegistration):
            raise ValueError("invalid PawApp setup entry registration")
        descriptor = registration.descriptor
        key = (plugin_id, descriptor.id)
        if key in self._pawapp_setup_entries:
            raise ValueError("PawApp setup entry already registered")
        frozen = type(descriptor).model_validate_json(
            descriptor.model_dump_json(),
        )
        self._pawapp_setup_entries[key] = SetupEntryRegistration(
            descriptor=frozen,
            opener=registration.opener,
        )

    def get_pawapp_setup_entries(self) -> Dict[tuple[str, str], Any]:
        return self._pawapp_setup_entries.copy()

    def register_pawapp_capability_imports(
        self,
        plugin_id: str,
        *,
        host_tools: List[str],
        host_skills: Dict[str, tuple[str, ...]],
    ) -> None:
        """Freeze the Host capabilities requested by one App manifest."""
        if plugin_id in self._pawapp_host_tools:
            raise ValueError("PawApp capability imports already registered")
        tools = tuple(host_tools)
        if len(set(tools)) != len(tools) or any(not name for name in tools):
            raise ValueError(
                "Host Tool imports must be unique non-empty names",
            )
        if any(not name for name in host_skills):
            raise ValueError("Host Skill imports require non-empty names")
        if any(
            not ref or len(refs) != len(set(refs))
            for refs in host_skills.values()
            for ref in refs
        ):
            raise ValueError(
                "Host Skill tool refs must be unique non-empty names",
            )
        self._pawapp_host_tools[plugin_id] = frozenset(tools)
        self._pawapp_host_skills[plugin_id] = {
            name: tuple(refs) for name, refs in host_skills.items()
        }

    def register_pawapp_local_tool(
        self,
        plugin_id: str,
        *,
        name: str,
        func: Callable,
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
        is_read_only: bool = False,
    ) -> None:
        """Register a private tool without publishing it to Host agents."""
        key = (plugin_id, name)
        if not name or not callable(func) or key in self._pawapp_local_tools:
            raise ValueError("PawApp local tool already registered or invalid")
        self._pawapp_local_tools[key] = PawAppLocalToolRegistration(
            plugin_id=plugin_id,
            name=name,
            func=func,
            description=description,
            input_schema=(
                dict(input_schema) if input_schema is not None else None
            ),
            is_read_only=is_read_only,
        )

    def register_pawapp_local_skills(
        self,
        plugin_id: str,
        directory: Any,
    ) -> None:
        """Register a private Skill root for one App only."""
        directories = self._pawapp_local_skill_dirs.setdefault(plugin_id, [])
        if directory in directories:
            raise ValueError("PawApp local Skill directory already registered")
        directories.append(directory)

    def get_pawapp_capabilities(self, plugin_id: str) -> Dict[str, Any]:
        """Return a detached capability view for a scoped broker request."""
        return {
            "host_tools": set(self._pawapp_host_tools.get(plugin_id, ())),
            "host_skills": dict(self._pawapp_host_skills.get(plugin_id, {})),
            "local_tools": {
                name: registration
                for (
                    owner,
                    name,
                ), registration in self._pawapp_local_tools.items()
                if owner == plugin_id
            },
            "local_skill_dirs": list(
                self._pawapp_local_skill_dirs.get(plugin_id, ()),
            ),
        }

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

        Clears manifest, providers, hooks, channels, and control commands
        that were registered under the given plugin_id.  Does not
        touch disk or agent configurations.

        Args:
            plugin_id: Plugin identifier to remove
        """
        from qwenpaw.memory import memory_registry

        self.assert_memory_backends_not_in_use(plugin_id)

        self._unregister_plugin_http_routes(plugin_id)
        self._unregister_plugin_channels(plugin_id)
        self._task_actions = {
            key: value
            for key, value in self._task_actions.items()
            if key[0] != plugin_id
        }
        self._pawapp_setup_checks = {
            key: value
            for key, value in self._pawapp_setup_checks.items()
            if key[0] != plugin_id
        }
        self._pawapp_setup_entries = {
            key: value
            for key, value in self._pawapp_setup_entries.items()
            if key[0] != plugin_id
        }
        self._pawapp_host_tools.pop(plugin_id, None)
        self._pawapp_host_skills.pop(plugin_id, None)
        self._pawapp_local_tools = {
            key: value
            for key, value in self._pawapp_local_tools.items()
            if key[0] != plugin_id
        }
        self._pawapp_local_skill_dirs.pop(plugin_id, None)

        try:
            removed_memory = memory_registry.unregister_owner(plugin_id)
            for backend_id in removed_memory:
                logger.info(
                    "Unregistered memory backend '%s' for plugin '%s'",
                    backend_id,
                    plugin_id,
                )
        except Exception:  # noqa: BLE001
            logger.debug(
                "Memory backend ownership release skipped for plugin %s",
                plugin_id,
                exc_info=True,
            )

        try:
            from .api import release_tool_ownership_for_plugin

            release_tool_ownership_for_plugin(plugin_id)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Tool ownership release skipped for plugin %s",
                plugin_id,
                exc_info=True,
            )

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
        self._uninstall_hooks = [
            h for h in self._uninstall_hooks if h.plugin_id != plugin_id
        ]
        self._workspace_created_hooks = [
            h
            for h in self._workspace_created_hooks
            if h.plugin_id != plugin_id
        ]
        self._control_commands = [
            c for c in self._control_commands if c.plugin_id != plugin_id
        ]
        self._middleware_registrations = [
            r
            for r in self._middleware_registrations
            if r.plugin_id != plugin_id
        ]
        removed_sections = [
            s for s in self._prompt_sections if s.plugin_id == plugin_id
        ]
        self._prompt_sections = [
            s for s in self._prompt_sections if s.plugin_id != plugin_id
        ]
        for s in removed_sections:
            self._prompt_section_names.discard(s.name)
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

    def assert_memory_backends_not_in_use(self, plugin_id: str) -> None:
        """Protect selected, starting, and draining memory backends."""
        from qwenpaw.memory import memory_registry

        owned_memory = set(memory_registry.owned_by(plugin_id))
        if not owned_memory:
            return
        selected_agent_ids: set[str] = set()
        if self._workspace_manager is not None:
            workspaces = getattr(
                self._workspace_manager,
                "agents",
                getattr(self._workspace_manager, "workspaces", {}),
            )
            selected_agent_ids.update(
                workspace.agent_id
                for workspace in workspaces.values()
                if getattr(
                    getattr(
                        getattr(workspace, "_config", None),
                        "running",
                        None,
                    ),
                    "memory_manager_backend",
                    None,
                )
                in owned_memory
            )
        in_use = memory_registry.begin_owner_unload(
            plugin_id,
            tuple(selected_agent_ids),
        )
        if in_use:
            raise RuntimeError(
                f"Cannot unload plugin '{plugin_id}'; memory backend is "
                f"in use by agents: {', '.join(sorted(in_use))}",
            )
