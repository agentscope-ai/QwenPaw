# -*- coding: utf-8 -*-
"""Plugin API for plugin developers."""

import logging
from pathlib import Path
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


# -------------------------------------------------------------------
# Helpers for PluginApi.register_tool
# -------------------------------------------------------------------


def _bridge_to_runtime(
    tool_name: str,
    tool_func: Callable,
    enabled: bool,
    description: str,
    registry,
) -> None:
    """Attach ToolDescriptor and inject into runtime ToolRegistries."""
    import inspect

    from ..runtime.tool_registry import ToolDescriptor

    desc = getattr(tool_func, "_tool_descriptor", None)
    if desc is None:
        is_async = inspect.iscoroutinefunction(tool_func)
        desc = ToolDescriptor(
            name=tool_name,
            func=tool_func,
            enabled_by_default=enabled,
            async_execution=is_async,
            description=description,
        )
        # pylint: disable-next=protected-access
        tool_func._tool_descriptor = desc  # type: ignore[attr-defined]
        logger.info(
            "Attached ToolDescriptor to '%s'",
            tool_name,
        )

    if registry is None:
        return
    wm = registry.get_workspace_manager()
    if wm is None:
        return

    for ws in getattr(wm, "agents", {}).values():
        tr = getattr(
            getattr(ws, "plugins", None),
            "tool_registry",
            None,
        )
        if tr is None or tool_name in tr:
            continue
        try:
            tr.register(desc)
            logger.info(
                "Injected '%s' into workspace '%s' ToolRegistry",
                tool_name,
                ws.agent_id,
            )
        except (ValueError, TypeError):
            pass

    bk = getattr(wm, "_bootstrap_kwargs", None)
    if bk is not None:
        funcs = bk.setdefault("builtin_tool_funcs", [])
        if tool_func not in funcs:
            funcs.append(tool_func)


def _write_tool_config(
    tool_name: str,
    enabled: bool,
    description: str,
    icon: str,
) -> None:
    """Persist BuiltinToolConfig entry to the agent config file."""
    from ..config.config import (
        BuiltinToolConfig,
        load_agent_config,
        save_agent_config,
    )
    from ..app.agent_context import get_current_agent_id

    agent_id = get_current_agent_id()
    if not agent_id:
        logger.warning(
            "No current agent ID; tool '%s' "
            "will be available after restart",
            tool_name,
        )
        return

    agent_config = load_agent_config(agent_id)

    if not agent_config.tools:
        from ..config.config import ToolsConfig

        agent_config.tools = ToolsConfig()

    if tool_name not in agent_config.tools.builtin_tools:
        agent_config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
            name=tool_name,
            enabled=enabled,
            description=description,
            display_to_user=True,
            async_execution=False,
            icon=icon,
        )
        logger.info(
            "Added tool '%s' to agent '%s' config (enabled=%s)",
            tool_name,
            agent_id,
            enabled,
        )
    else:
        logger.info(
            "Tool '%s' already in agent '%s' config, skipping",
            tool_name,
            agent_id,
        )

    save_agent_config(agent_id, agent_config)


# -------------------------------------------------------------------


class PluginApi:  # pylint: disable=too-many-public-methods
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

    def register_uninstall_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register an uninstall hook.

        Unlike shutdown hooks (which run on every app shutdown),
        uninstall hooks run **only** when the plugin is explicitly
        unloaded or removed via ``PluginLoader.unload_plugin()``.

        Use these for one-time cleanup on uninstall — e.g. removing
        workspace skills, clearing manifest entries, or undoing
        monkey-patches applied during startup.

        The callback receives keyword arguments:
            - ``plugin_id`` (str): The plugin being uninstalled.
            - ``delete_files`` (bool): Whether files are being deleted.

        Args:
            hook_name: Unique hook identifier
            callback: Async or sync function to call on uninstall.
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_uninstall_hook(
            ...     hook_name="cleanup_skills",
            ...     callback=self.on_uninstall,
            ... )
        """
        if self._registry:
            self._registry.register_uninstall_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered uninstall hook "
                f"'{hook_name}' (priority={priority})",
            )

    def register_workspace_created_hook(
        self,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a hook that fires when a new workspace is created.

        The callback receives a single ``workspace_info`` dict with at
        least ``agent_id`` (str) and ``workspace_dir`` (str) keys.

        Args:
            hook_name: Unique hook identifier
            callback: Sync or async function to call on workspace creation.
                Signature: ``(workspace_info: dict) -> None``
            priority: Execution priority (lower = earlier, default=100)

        Example:
            >>> api.register_workspace_created_hook(
            ...     hook_name="provision_new_workspace",
            ...     callback=self.on_workspace_created,
            ... )
        """
        if self._registry:
            self._registry.register_workspace_created_hook(
                plugin_id=self.plugin_id,
                hook_name=hook_name,
                callback=callback,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered "
                f"workspace_created hook '{hook_name}' "
                f"(priority={priority})",
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

    def register_middleware(
        self,
        middleware_factory: Callable,
        *,
        priority: int = 100,
    ) -> None:
        """Register an AgentScope MiddlewareBase factory.

        The factory is called once per request during agent assembly:
            ``factory(ctx, agent_config) -> MiddlewareBase | None``

        Returning None means the middleware is skipped for this request.
        Priority controls ordering (lower = outermost in onion model).

        Args:
            middleware_factory: Callable that receives ``(ctx, agent_config)``
                and returns a ``MiddlewareBase`` instance or None.
            priority: Ordering priority (lower = outermost). Default: 100.

        Example:
            >>> def my_factory(ctx, agent_config):
            ...     return MyMiddleware()
            >>> api.register_middleware(my_factory, priority=50)
        """
        if self._registry:
            self._registry.register_middleware(
                plugin_id=self.plugin_id,
                factory=middleware_factory,
                priority=priority,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered middleware "
                f"factory (priority={priority})",
            )

    def register_channel(
        self,
        channel_class: Type,
        label: str = "",
        description: str = "",
        config_fields: Optional[List[Dict[str, Any]]] = None,
        icon: str = "",
        doc_url: Any = "",
    ) -> None:
        """Register a custom messaging channel.

        The channel_class must be a concrete subclass of
        ``qwenpaw.app.channels.base.BaseChannel`` with a ``channel``
        class attribute that serves as the unique key.

        Args:
            channel_class: BaseChannel subclass implementing the channel.
                Must have a ``channel`` class attribute (used as key).
            label: Display name shown in the UI (defaults to channel key).
            description: Short description for the UI.
            config_fields: List of config field descriptors for the
                frontend settings form.  Each dict should contain:
                - name (str): field key in the config
                - label (str): display label
                - type (str): "text" | "password" | "number" | "switch"
                    | "select"
                - required (bool, optional): default False
                - placeholder (str, optional)
                - help (str, optional): tooltip text
                - default (Any, optional): default value
                - options (list, optional): for "select" type
            icon: Optional channel card icon URL. The Console falls back
                to the default icon when it is empty or not a usable
                http(s) URL.
            doc_url: Optional documentation link. May be a plain http(s)
                URL string, or a localized mapping such as
                ``{"zh": "...", "en": "..."}``. The Console shows a "Doc"
                button only when it resolves to a usable http(s) URL.

        Example:
            >>> api.register_channel(
            ...     channel_class=SlackChannel,
            ...     label="Slack",
            ...     description="Slack workspace integration",
            ...     config_fields=[
            ...         {
            ...             "name": "bot_token",
            ...             "label": "Bot Token",
            ...             "type": "password",
            ...             "required": True,
            ...             "placeholder": "xoxb-...",
            ...         },
            ...         {
            ...             "name": "signing_secret",
            ...             "label": "Signing Secret",
            ...             "type": "password",
            ...             "required": True,
            ...         },
            ...     ],
            ... )
        """
        if not self._registry:
            logger.warning(
                f"Plugin '{self.plugin_id}' cannot register channel: "
                f"registry unavailable",
            )
            return

        channel_key = getattr(channel_class, "channel", None)
        if not channel_key:
            raise ValueError(
                f"channel_class {channel_class!r} must have a "
                f"'channel' class attribute as the channel key",
            )
        self._registry.register_channel(
            plugin_id=self.plugin_id,
            channel_key=channel_key,
            channel_class=channel_class,
            label=label,
            description=description,
            config_fields=config_fields,
            icon=icon,
            doc_url=doc_url,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' registered channel "
            f"'{channel_key}'",
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
        - Bridges to the runtime ToolRegistry so the agent can
          actually invoke the tool at runtime.

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

                _bridge_to_runtime(
                    tool_name,
                    tool_func,
                    enabled,
                    description,
                    self._registry,
                )
                _write_tool_config(
                    tool_name,
                    enabled,
                    description,
                    icon,
                )

            except Exception as exc:
                logger.error(
                    f"Failed to register tool '{tool_name}': {exc}",
                    exc_info=True,
                )

        self.register_startup_hook(
            hook_name=(f"register_tool_{self.plugin_id}_{tool_name}"),
            callback=_startup_register,
            priority=50,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled tool "
            f"'{tool_name}' for registration on startup",
        )

    def register_slash_command(
        self,
        name: str,
        handler: Callable,
        *,
        aliases: tuple = (),
        category: str = "plugin",
        help_text: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a slash command into per-workspace registries.

        The command appears as ``/name`` in the chat input and is
        dispatched through ``SlashCommandRegistry.dispatch()``.

        Registration is deferred to a startup hook so it runs after
        workspaces are fully initialized.

        Args:
            name: Command name (without leading ``/``).
            handler: Async callable ``(ctx, args) -> Msg | None``.
            aliases: Extra names that resolve to the same handler.
            category: Origin tag for introspection.
            help_text: Human-readable description shown in menus.
            metadata: Arbitrary key-value metadata.
        """
        from ..runtime.slash_command_registry import CommandSpec

        spec = CommandSpec(
            name=name,
            handler=handler,
            aliases=aliases,
            category=category,
            help_text=help_text,
            metadata=metadata or {},
        )

        def _register_to_workspaces():
            self._register_spec_to_all_workspaces(spec)

        def _on_workspace_created(workspace_info: dict):
            self._register_spec_to_workspace(spec, workspace_info)

        self.register_startup_hook(
            hook_name=(f"slash_cmd_{self.plugin_id}_{name}"),
            callback=_register_to_workspaces,
            priority=60,
        )
        self.register_workspace_created_hook(
            hook_name=(f"slash_cmd_ws_{self.plugin_id}_{name}"),
            callback=_on_workspace_created,
            priority=60,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled slash command "
            f"'/{name}' for registration",
        )

    def register_mode(
        self,
        mode_cls: Type,
    ) -> None:
        """Register a plugin-contributed AgentMode.

        The mode is instantiated and registered into every workspace
        on startup, and into newly created workspaces via a
        workspace_created hook. Runtime lifecycle callbacks receive
        the current ``HookContext``.

        Args:
            mode_cls: An ``AgentMode`` subclass with a unique
                ``name`` class attribute.
        """
        mode_instance = mode_cls()

        def _register_mode():
            self._register_mode_to_all_workspaces(mode_instance)

        def _on_workspace_created(workspace_info: dict):
            self._register_mode_to_workspace(
                mode_instance,
                workspace_info,
            )

        self.register_startup_hook(
            hook_name=(f"mode_{self.plugin_id}_{mode_instance.name}"),
            callback=_register_mode,
            priority=70,
        )
        self.register_workspace_created_hook(
            hook_name=(f"mode_ws_{self.plugin_id}_{mode_instance.name}"),
            callback=_on_workspace_created,
            priority=70,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled mode "
            f"'{mode_instance.name}' for registration",
        )

    def register_runtime_hook(
        self,
        hook: Any,
    ) -> None:
        """Register a runtime-phase hook.

        The hook is registered into every workspace's HookRegistry
        on startup. See ``runtime.phases.Phase`` for the 8 available
        phases.

        Args:
            hook: A ``HookBase`` subclass instance with ``phase``,
                ``name``, and ``run()`` defined.
        """

        def _register_hook():
            self._register_hook_to_all_workspaces(hook)

        def _on_workspace_created(workspace_info: dict):
            self._register_hook_to_workspace(
                hook,
                workspace_info,
            )

        self.register_startup_hook(
            hook_name=(f"rt_hook_{self.plugin_id}_{hook.name}"),
            callback=_register_hook,
            priority=65,
        )
        self.register_workspace_created_hook(
            hook_name=(f"rt_hook_ws_{self.plugin_id}_{hook.name}"),
            callback=_on_workspace_created,
            priority=65,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled runtime hook "
            f"'{hook.name}' (phase={hook.phase})",
        )

    def register_agent_stop_handler(
        self,
        handler: Callable,
        *,
        priority: int = 100,
        name: str = "",
    ) -> None:
        """Register a handler for agent stop events.

        When the agent decides to stop, the stop handler chain is
        evaluated. A handler can return BLOCK with a continuation
        message to keep the agent running.

        Args:
            handler: Async callable ``(ctx) -> StopHandlerResult``.
            priority: Lower number = higher priority.
            name: Human-readable name for debugging.
        """
        from ..loop.gates import (
            StopHandlerRegistration,
        )

        reg = StopHandlerRegistration(
            plugin_id=self.plugin_id,
            handler=handler,
            priority=priority,
            name=name or f"{self.plugin_id}_stop",
        )

        def _register():
            self._register_stop_handler_to_all_workspaces(reg)

        def _on_workspace_created(workspace_info: dict):
            self._register_stop_handler_to_workspace(
                reg,
                workspace_info,
            )

        self.register_startup_hook(
            hook_name=(f"stop_{self.plugin_id}_{reg.name}"),
            callback=_register,
            priority=55,
        )
        self.register_workspace_created_hook(
            hook_name=(f"stop_ws_{self.plugin_id}_{reg.name}"),
            callback=_on_workspace_created,
            priority=55,
        )
        logger.info(
            f"Plugin '{self.plugin_id}' scheduled stop handler "
            f"'{reg.name}' (priority={priority})",
        )

    def register_prompt_section(
        self,
        name: str,
        after: str,
        provider: Callable,
        *,
        priority: int = 100,
        condition: Optional[Callable] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """Register a system prompt section.

        The section is injected into the system prompt after the
        specified anchor. When ``condition`` is provided, the section
        is only included if the callable returns True.

        Args:
            name: Unique section name.
            after: Host anchor this section follows
                (workspace/multimodal/env_context).
            provider: Callable ``(agent) -> str`` returning text.
            priority: Order within same anchor (lower = earlier).
            condition: Optional ``(ctx) -> bool`` gate.
            agent_id: Optional agent filter; None = global.
        """
        if condition is not None:
            original_provider = provider

            def _gated_provider(
                agent,
                _cond=condition,
                _prov=original_provider,
            ):
                try:
                    if not _cond(agent):
                        return ""
                except Exception as exc:
                    logger.warning(
                        "Prompt condition error: %s",
                        exc,
                    )
                    return ""
                return _prov(agent)

            provider = _gated_provider

        if self._registry:
            self._registry.register_prompt_section(
                plugin_id=self.plugin_id,
                name=name,
                after=after,
                agent_id=agent_id,
                provider=provider,
            )
            logger.info(
                f"Plugin '{self.plugin_id}' registered prompt "
                f"section '{name}' after '{after}' "
                f"(priority={priority})",
            )

    # ================================================================
    # Internal helpers for workspace registration
    # ================================================================

    def _get_all_workspaces(self) -> list:
        """Get all workspace instances from the registry."""
        try:
            from .registry import PluginRegistry

            registry = PluginRegistry()
            mgr = registry.get_workspace_manager()
            if mgr is None:
                return []
            return list(mgr.agents.values())
        except Exception as exc:
            logger.debug(
                f"Could not get workspaces: {exc}",
            )
            return []

    def _get_workspace_from_info(
        self,
        workspace_info: dict,
    ):
        """Get workspace instance from workspace_info dict."""
        try:
            from .registry import PluginRegistry

            agent_id = workspace_info.get("agent_id")
            if not agent_id:
                return None
            registry = PluginRegistry()
            mgr = registry.get_workspace_manager()
            if mgr is None:
                return None
            return mgr.agents.get(agent_id)
        except Exception as exc:
            logger.warning(
                "Get workspace error: %s",
                exc,
            )
            return None

    def _register_spec_to_all_workspaces(self, spec):
        """Register a CommandSpec to all existing workspaces."""
        for ws in self._get_all_workspaces():
            try:
                ws.plugins.slash_command_registry.register(spec)
            except ValueError as exc:
                logger.debug(
                    f"Slash cmd already registered: {exc}",
                )

    def _register_spec_to_workspace(
        self,
        spec,
        workspace_info: dict,
    ):
        """Register a CommandSpec to a specific workspace."""
        ws = self._get_workspace_from_info(workspace_info)
        if ws is None:
            return
        try:
            ws.plugins.slash_command_registry.register(spec)
        except ValueError as exc:
            logger.debug(
                f"Slash cmd already registered: {exc}",
            )

    def _register_mode_to_all_workspaces(self, mode):
        """Register an AgentMode to all workspaces."""
        for ws in self._get_all_workspaces():
            try:
                ws.plugins.register_mode(mode, ws)
            except ValueError as exc:
                logger.debug(
                    f"Mode already registered: {exc}",
                )

    def _register_mode_to_workspace(
        self,
        mode,
        workspace_info: dict,
    ):
        """Register an AgentMode to a specific workspace."""
        ws = self._get_workspace_from_info(workspace_info)
        if ws is None:
            return
        try:
            ws.plugins.register_mode(mode, ws)
        except ValueError as exc:
            logger.debug(
                f"Mode already registered: {exc}",
            )

    def _register_hook_to_all_workspaces(self, hook):
        """Register a runtime hook to all workspaces."""
        for ws in self._get_all_workspaces():
            try:
                ws.plugins.hook_registry.register(hook)
            except (TypeError, ValueError) as exc:
                logger.debug(
                    f"Hook registration issue: {exc}",
                )

    def _register_hook_to_workspace(
        self,
        hook,
        workspace_info: dict,
    ):
        """Register a runtime hook to a specific workspace."""
        ws = self._get_workspace_from_info(workspace_info)
        if ws is None:
            return
        try:
            ws.plugins.hook_registry.register(hook)
        except (TypeError, ValueError) as exc:
            logger.debug(
                f"Hook registration issue: {exc}",
            )

    def _register_stop_handler_to_all_workspaces(self, reg):
        """Register stop handler to all workspaces."""
        for ws in self._get_all_workspaces():
            self._attach_stop_handler(ws, reg)

    def _register_stop_handler_to_workspace(
        self,
        reg,
        workspace_info: dict,
    ):
        """Register stop handler to a specific workspace."""
        ws = self._get_workspace_from_info(workspace_info)
        if ws is None:
            return
        self._attach_stop_handler(ws, reg)

    @staticmethod
    def _attach_stop_handler(ws, reg):
        """Attach a stop handler registration to workspace."""
        if not hasattr(ws.plugins, "stop_handlers"):
            ws.plugins.stop_handlers = []
        ws.plugins.stop_handlers.append(reg)

    # ================================================================
    # End Loop Engineering
    # ================================================================

    def register_skill_provider(
        self,
        skills_dir: Path,
        *,
        enabled_by_default: bool = True,
        channels: Optional[List[str]] = None,
    ) -> None:
        """Register a plugin as a skill provider.

        Copies the plugin's skills into the workspace skill directory,
        reconciles the workspace manifest, and applies the plugin's
        default enable/channel strategy.  On uninstall, skills sourced
        from this plugin are automatically cleaned up.

        Skills are also automatically installed into workspaces created
        after the server starts, via a ``workspace_created`` hook.

        The host handles:
        - Copying the skill directory into the workspace.
        - Reconciling the workspace skill manifest.
        - Applying the default enabled/channels strategy.
        - Cleaning up manifest entries on uninstall (by ``source``).

        Args:
            skills_dir: Path to the directory containing the plugin's
                skill sub-directories (each with a ``SKILL.md``).
            enabled_by_default: Whether the skills should be enabled
                immediately after installation. Default: True.
            channels: List of channel names the skills apply to, or
                ``["all"]`` for all channels. Default: ``["all"]``.

        Example:
            >>> from pathlib import Path
            >>> PLUGIN_DIR = Path(__file__).parent
            >>> api.register_skill_provider(
            ...     skills_dir=PLUGIN_DIR / "skills",
            ...     enabled_by_default=True,
            ...     channels=["all"],
            ... )
        """
        skills_dir = Path(skills_dir)
        resolved_channels = channels or ["all"]
        source_tag = f"plugin:{self.plugin_id}"

        def _install_skills():
            self._do_install_skills(
                skills_dir,
                source_tag,
                enabled_by_default,
                resolved_channels,
            )

        def _uninstall_skills(plugin_id: str, delete_files: bool = False):
            """Remove skills sourced from this plugin on uninstall."""
            _ = delete_files  # unused but part of uninstall hook contract
            self._do_uninstall_skills(plugin_id, source_tag)

        def _on_workspace_created(workspace_info: dict):
            """Install plugin skills into a newly created workspace."""
            self._install_skills_into_workspace(
                workspace_info,
                skills_dir,
                source_tag,
                enabled_by_default,
                resolved_channels,
            )

        # Register skill installation on startup
        self.register_startup_hook(
            hook_name=f"install_skills_{self.plugin_id}",
            callback=_install_skills,
            priority=80,
        )

        # Register hook to provision newly created workspaces
        self.register_workspace_created_hook(
            hook_name=f"provision_skills_{self.plugin_id}",
            callback=_on_workspace_created,
            priority=80,
        )

        # Register cleanup on uninstall
        self.register_uninstall_hook(
            hook_name=f"uninstall_skills_{self.plugin_id}",
            callback=_uninstall_skills,
        )

    def unregister_skill_provider(self) -> None:
        """Unregister this plugin as a skill provider.

        Removes the startup, workspace_created, and uninstall hooks
        that were registered by ``register_skill_provider()``, and
        cleans up skills sourced from this plugin across all existing
        workspaces.

        This allows plugins to dynamically disable their skill
        provider without requiring a full plugin uninstall.

        Example:
            >>> api.unregister_skill_provider()
        """
        source_tag = f"plugin:{self.plugin_id}"
        hook_names = [
            f"install_skills_{self.plugin_id}",
            f"provision_skills_{self.plugin_id}",
            f"uninstall_skills_{self.plugin_id}",
        ]

        # Remove the hooks from registry
        if self._registry:
            self._registry.remove_hooks_by_name(
                self.plugin_id,
                hook_names,
            )

        # Clean up already-installed skills
        self._do_uninstall_skills(self.plugin_id, source_tag)

        logger.info(
            f"Plugin '{self.plugin_id}' unregistered as skill provider",
        )

    def _get_skill_names(self, skills_dir: Path) -> List[str]:
        """Return sub-directory names that contain a SKILL.md file."""
        if not skills_dir.exists() or not skills_dir.is_dir():
            logger.warning(
                f"Plugin '{self.plugin_id}' skills_dir "
                f"does not exist: {skills_dir}",
            )
            return []
        return [
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        ]

    def _install_skills_into_workspace(
        self,
        workspace_info: dict,
        skills_dir: Path,
        source_tag: str,
        enabled_by_default: bool,
        resolved_channels: List[str],
    ) -> None:
        """Copy plugin skills into a single workspace and update its manifest.

        This is the shared implementation used by both the startup hook
        (for all existing workspaces) and the workspace_created hook
        (for newly created workspaces).
        """
        try:
            from ..agents.skill_system.store import (
                copy_skill_dir,
                get_workspace_skills_dir,
                get_workspace_skill_manifest_path,
                default_workspace_manifest,
                mutate_json,
            )
            from ..agents.skill_system.registry import (
                reconcile_workspace_manifest,
            )

            skill_names = self._get_skill_names(skills_dir)
            if not skill_names:
                return

            workspace_dir = Path(workspace_info["workspace_dir"])
            ws_skills_dir = get_workspace_skills_dir(workspace_dir)
            ws_skills_dir.mkdir(parents=True, exist_ok=True)

            for skill_name in skill_names:
                copy_skill_dir(
                    skills_dir / skill_name,
                    ws_skills_dir / skill_name,
                )

            reconcile_workspace_manifest(workspace_dir)

            manifest_path = get_workspace_skill_manifest_path(
                workspace_dir,
            )

            def _apply_defaults(
                payload,
                _names=tuple(skill_names),
                _src=source_tag,
                _enabled=enabled_by_default,
                _channels=tuple(resolved_channels),
            ):
                skills = payload.setdefault("skills", {})
                for name in _names:
                    entry = skills.get(name)
                    if entry is None:
                        continue
                    if entry.get("source") != _src:
                        entry["enabled"] = _enabled
                        entry["channels"] = list(_channels)
                    entry["source"] = _src
                return payload

            mutate_json(
                manifest_path,
                default_workspace_manifest(),
                _apply_defaults,
            )

            logger.debug(
                f"Plugin '{self.plugin_id}' installed "
                f"{len(skill_names)} skill(s) into workspace "
                f"'{workspace_info.get('agent_id', '?')}'",
            )
        except Exception as exc:
            logger.error(
                f"Failed to install skills for plugin "
                f"'{self.plugin_id}' into workspace "
                f"'{workspace_info.get('agent_id', '?')}': {exc}",
                exc_info=True,
            )

    def _do_install_skills(
        self,
        skills_dir: Path,
        source_tag: str,
        enabled_by_default: bool,
        resolved_channels: List[str],
    ) -> None:
        """Copy plugin skills into all existing workspaces."""
        try:
            from ..agents.skill_system.registry import list_workspaces

            skill_names = self._get_skill_names(skills_dir)
            if not skill_names:
                return

            workspaces = list_workspaces()
            for workspace_info in workspaces:
                self._install_skills_into_workspace(
                    workspace_info,
                    skills_dir,
                    source_tag,
                    enabled_by_default,
                    resolved_channels,
                )

            logger.info(
                f"Plugin '{self.plugin_id}' installed "
                f"{len(skill_names)} skill(s) into "
                f"{len(workspaces)} workspace(s)",
            )
        except Exception as exc:
            logger.error(
                f"Failed to install skills for plugin "
                f"'{self.plugin_id}': {exc}",
                exc_info=True,
            )

    @staticmethod
    def _do_uninstall_skills(plugin_id: str, source_tag: str) -> None:
        """Remove skills sourced from a plugin across all workspaces."""
        try:
            import shutil

            from ..agents.skill_system.store import (
                get_workspace_skills_dir,
                get_workspace_skill_manifest_path,
                default_workspace_manifest,
                mutate_json,
            )
            from ..agents.skill_system.registry import (
                list_workspaces,
            )

            workspaces = list_workspaces()
            for workspace_info in workspaces:
                workspace_dir = Path(workspace_info["workspace_dir"])
                ws_skills_dir = get_workspace_skills_dir(workspace_dir)
                manifest_path = get_workspace_skill_manifest_path(
                    workspace_dir,
                )

                # NOTE: The closure captures loop variables via default args.
                # This is safe because mutate_json is called synchronously
                # immediately below.  If mutate_json ever becomes async or
                # deferred, these must be refactored to explicit arguments.
                def _remove_plugin_skills(
                    payload,
                    _ws_skills=ws_skills_dir,
                    _tag=source_tag,
                    _agent_id=workspace_info["agent_id"],
                ):
                    skills = payload.setdefault("skills", {})
                    to_remove = [
                        name
                        for name, entry in skills.items()
                        if entry.get("source") == _tag
                    ]
                    for name in to_remove:
                        skills.pop(name, None)
                        skill_dir = _ws_skills / name
                        if skill_dir.exists():
                            try:
                                shutil.rmtree(skill_dir)
                            except OSError as rmtree_exc:
                                logger.warning(
                                    "Failed to fully remove skill "
                                    "directory %s: %s",
                                    skill_dir,
                                    rmtree_exc,
                                )
                    if to_remove:
                        logger.info(
                            "Removed skills %s from workspace '%s'",
                            to_remove,
                            _agent_id,
                        )
                    return payload

                mutate_json(
                    manifest_path,
                    default_workspace_manifest(),
                    _remove_plugin_skills,
                )

            logger.info(
                "Plugin '%s' skills cleaned up from %d workspace(s)",
                plugin_id,
                len(workspaces),
            )
        except Exception as exc:
            logger.error(
                "Failed to uninstall skills for plugin '%s': %s",
                plugin_id,
                exc,
                exc_info=True,
            )
