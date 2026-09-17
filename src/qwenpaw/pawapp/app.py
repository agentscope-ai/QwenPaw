# -*- coding: utf-8 -*-
"""PawApp class — Developer-facing SDK entry point.

Wraps PluginApi under the hood. Provides decorator sugar for:
- ``@app.route(path)`` — register HTTP route
- ``@app.tool(name, desc)`` — register agent tool
- ``@app.command(name, desc)`` — register /slash command
- ``@app.hook(phase)`` — register lifecycle hook
- ``app.include_router(router)`` — mount a FastAPI Router

Example (decorator mode):
    from qwenpaw.pawapp import PawApp

    app = PawApp()

    @app.route("/review")
    async def review(ctx, file: bytes, style: str = "严格"):
        reply = await ctx.chat(f"审稿: {style}")
        return {"review": reply.text}

Example (router mode):
    from qwenpaw.pawapp import PawApp, get_ctx
    from fastapi import APIRouter, Depends

    app = PawApp()
    router = APIRouter()

    @router.get("/projects")
    async def list_projects(ctx=Depends(get_ctx)):
        return await ctx.storage.get("projects", default=[])

    app.include_router(router)
"""

from __future__ import annotations

import inspect
import logging
from functools import wraps
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends, Request

from .deps import get_ctx

logger = logging.getLogger(__name__)


def _make_app_id_injector(app_id: str) -> Callable:
    """Create a dependency that injects app_id into request.state.

    This ensures get_ctx can retrieve the correct app_id from request.state
    without relying on URL regex parsing.
    """

    async def inject_app_id(request: Request) -> None:
        request.state.app_id = app_id

    return inject_app_id


class PawApp:
    """PawApp SDK — thin wrapper over QwenPaw's Plugin API.

    In the plugin loading pipeline, ``PawApp.register(api)`` is called
    by the PluginLoader, which injects the real ``PluginApi`` instance.
    Before that, decorator registrations are buffered.
    """

    def __init__(self, name: str = "", *, app_id: str = ""):
        self.name = name
        self.app_id = app_id
        self._plugin_api: Any = None  # set by PluginLoader via .register(api)

        # Internal router for decorator-mode routes
        self._router = APIRouter()

        # Buffered registrations (applied when .register(api) is called)
        self._tools: List[dict] = []
        self._commands: List[dict] = []
        self._hooks: List[dict] = []
        self._routers: List[APIRouter] = []
        self._lifecycle: dict = {}

    # ─── Decorator: HTTP route ──────────────────────────────────────

    def route(self, path: str, *, methods: Optional[List[str]] = None):
        """Register a route handler on the app's internal router.

        The handler receives ``ctx`` as first positional argument
        (injected automatically by the SDK via ``get_ctx``).
        """
        if methods is None:
            methods = ["POST"]

        def decorator(func: Callable) -> Callable:
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())

            if params and params[0] == "ctx":

                @wraps(func)
                async def wrapper(
                    *args,
                    ctx=Depends(get_ctx),
                    **kwargs,
                ):
                    return await func(ctx, *args, **kwargs)

                for method in methods:
                    getattr(
                        self._router,
                        method.lower(),
                    )(
                        path,
                    )(wrapper)
            else:
                for method in methods:
                    getattr(
                        self._router,
                        method.lower(),
                    )(
                        path,
                    )(func)

            return func

        return decorator

    # ─── Decorator: tool ────────────────────────────────────────────

    def tool(
        self,
        name: str,
        *,
        description: str = "",
        icon: str = "🔧",
        enabled: bool = True,
    ):
        """Register a tool that the Agent can invoke during reasoning.

        ``enabled`` defaults to True so a PawApp's own tools are available
        to the agent immediately after install (a PawApp explicitly opts
        into exposing the tool). Set False to require manual opt-in.
        """

        def decorator(func: Callable) -> Callable:
            self._tools.append(
                {
                    "name": name,
                    "func": func,
                    "description": description,
                    "icon": icon,
                    "enabled": enabled,
                },
            )
            return func

        return decorator

    # ─── Decorator: command ─────────────────────────────────────────

    def command(self, name: str, *, description: str = ""):
        """Register a /slash control command."""

        def decorator(func: Callable) -> Callable:
            self._commands.append(
                {
                    "name": name,
                    "func": func,
                    "description": description,
                },
            )
            return func

        return decorator

    # ─── Decorator: hook ────────────────────────────────────────────

    def hook(self, phase: str, *, priority: int = 100):
        """Register a lifecycle hook (startup, shutdown, etc.)."""

        def decorator(func: Callable) -> Callable:
            self._hooks.append(
                {
                    "phase": phase,
                    "func": func,
                    "priority": priority,
                },
            )
            return func

        return decorator

    # ─── Lifecycle decorators ───────────────────────────────────────

    def on_install(self, func: Callable) -> Callable:
        """Decorator: called once when App is first installed."""
        self._lifecycle["install"] = func
        return func

    def on_launch(self, func: Callable) -> Callable:
        """Decorator: called each time the App session starts."""
        self._lifecycle["launch"] = func
        return func

    def on_terminate(self, func: Callable) -> Callable:
        """Decorator: called when session closes."""
        self._lifecycle["terminate"] = func
        return func

    def on_uninstall(self, func: Callable) -> Callable:
        """Decorator: called when App is removed."""
        self._lifecycle["uninstall"] = func
        return func

    # ─── Router inclusion ───────────────────────────────────────────

    def include_router(self, router: APIRouter, **kwargs) -> None:
        """Mount a FastAPI Router onto this PawApp."""
        # pylint: disable=unused-argument
        self._routers.append(router)

    # ─── Plugin registration (called by PluginLoader) ───────────────

    def register(self, api: Any) -> None:
        """Called by PluginLoader when the plugin is loaded.

        ``api`` is a ``PluginApi`` instance. We apply all buffered
        registrations now.
        """
        self._plugin_api = api

        # Create app_id injector dependency
        app_id_injector = Depends(_make_app_id_injector(self.app_id))

        # Mount internal router (decorator-mode routes)
        if self._router.routes:
            prefix = f"/{self.app_id}" if self.app_id else ""
            # Inject app_id into request.state for all routes
            if self._router.dependencies is None:
                self._router.dependencies = []
            self._router.dependencies.append(app_id_injector)
            api.register_http_router(
                self._router,
                prefix=prefix,
                tags=[f"pawapp:{self.app_id or self.name}"],
            )

        # Mount external routers
        for router in self._routers:
            prefix = f"/{self.app_id}" if self.app_id else ""
            # Inject app_id into request.state for all routes
            if router.dependencies is None:
                router.dependencies = []
            router.dependencies.append(app_id_injector)
            api.register_http_router(
                router,
                prefix=prefix,
                tags=[f"pawapp:{self.app_id or self.name}"],
            )

        # Register tools
        for tool_info in self._tools:
            api.register_tool(
                tool_name=tool_info["name"],
                tool_func=tool_info["func"],
                description=tool_info["description"],
                icon=tool_info["icon"],
                enabled=tool_info.get("enabled", True),
            )

        # Register startup/shutdown hooks
        for hook_info in self._hooks:
            phase = hook_info["phase"]
            if phase == "startup":
                api.register_startup_hook(
                    hook_name=f"pawapp_{self.app_id}_{id(hook_info['func'])}",
                    callback=hook_info["func"],
                    priority=hook_info["priority"],
                )
            elif phase == "shutdown":
                api.register_shutdown_hook(
                    hook_name=f"pawapp_{self.app_id}_{id(hook_info['func'])}",
                    callback=hook_info["func"],
                    priority=hook_info["priority"],
                )

        # Register lifecycle hooks via startup/shutdown
        if "install" in self._lifecycle:
            api.register_startup_hook(
                hook_name=f"pawapp_{self.app_id}_on_install",
                callback=self._lifecycle["install"],
                priority=90,
            )
        if "launch" in self._lifecycle:
            api.register_startup_hook(
                hook_name=f"pawapp_{self.app_id}_on_launch",
                callback=self._lifecycle["launch"],
                priority=100,
            )
        if "terminate" in self._lifecycle:
            api.register_shutdown_hook(
                hook_name=f"pawapp_{self.app_id}_on_terminate",
                callback=self._lifecycle["terminate"],
                priority=100,
            )
        if "uninstall" in self._lifecycle:
            api.register_uninstall_hook(
                hook_name=f"pawapp_{self.app_id}_on_uninstall",
                callback=self._lifecycle["uninstall"],
            )

        logger.info(
            "PawApp '%s' registered via PluginApi (routes=%d, tools=%d)",
            self.app_id or self.name,
            len(self._router.routes)
            + sum(len(r.routes) for r in self._routers),
            len(self._tools),
        )
