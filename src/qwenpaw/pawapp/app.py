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

import asyncio
import inspect
import logging
import re
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Mapping, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from qwenpaw.exceptions import ConfigurationException

from .deps import get_ctx, get_scoped_ctx
from .dependency import (
    DependencyHealth,
    DependencyLifecycle,
    DependencyProbe,
    DependencyRegistry,
    DependencySpec,
)
from .agent import ManagedAgentProfile, ManagedAgentProfileSpec
from .service import ManagedService, ManagedServiceSpec

logger = logging.getLogger(__name__)
_APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _ChatSessionCreate(BaseModel):
    name: str = Field(default="New analysis", max_length=80)


class _ChatSessionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class _ChatSessionPin(BaseModel):
    pinned: bool = True


def _resolve_app_session_id(ctx: Any, session_id: Optional[str]) -> str:
    """Resolve or validate the dialogue ID used by standard app routes.

    Standard capability routes only operate on server-minted dialogue IDs
    inside this app's ``pawapp:`` namespace. An absent ID selects the app's
    default dialogue; any explicit ID outside the namespace — a sibling
    app's namespace or an arbitrary host session key — is rejected so the
    routes can never read or append to a transcript the app does not own.
    Legacy PawApps that rely on custom session IDs keep that behavior on
    their own registered routes through the Python context API.
    """
    if not session_id:
        return f"pawapp:{ctx.app_id}"
    namespace = f"pawapp:{ctx.app_id}"
    owns_session = (
        ctx.is_app_session_id(session_id)
        if hasattr(ctx, "is_app_session_id")
        else session_id == namespace or session_id.startswith(f"{namespace}:")
    )
    if not owns_session:
        raise HTTPException(
            status_code=404,
            detail="Unknown session",
        )
    return session_id


def _configuration_error_detail(exc: ConfigurationException) -> dict:
    """Return an app-safe, actionable host configuration error."""
    detail = {
        "code": exc.error_code or "CONFIGURATION_REQUIRED",
        "message": exc.message or str(exc),
        "config_key": exc.config_key,
    }
    if exc.config_key == "active_model":
        detail["action"] = {
            "label": "Configure a model",
            "path": "/models",
        }
    return detail


def _build_capability_router() -> APIRouter:  # pylint: disable=R0915
    """Build the standard frontend-to-host routes every PawApp receives.

    Every route resolves its context through ``get_scoped_ctx``: identity
    comes from the authenticated principal, never from request parameters.
    """
    import json

    router = APIRouter()

    @router.post("/chat")
    async def chat(request: Request, ctx=Depends(get_scoped_ctx)):
        payload = await request.json()
        message = str(payload.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        session_id = _resolve_app_session_id(ctx, payload.get("session_id"))
        if hasattr(ctx, "ensure_chat_session"):
            await ctx.ensure_chat_session(session_id)
        try:
            reply = await ctx.chat(
                message,
                skill=payload.get("skill"),
                session_id=session_id,
            )
        except ConfigurationException as exc:
            raise HTTPException(
                status_code=503,
                detail=_configuration_error_detail(exc),
            ) from exc
        return {"text": reply.text}

    @router.post("/chat/stream")
    async def chat_stream(request: Request, ctx=Depends(get_scoped_ctx)):
        payload = await request.json()
        message = str(payload.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        session_id = _resolve_app_session_id(ctx, payload.get("session_id"))
        if hasattr(ctx, "ensure_chat_session"):
            await ctx.ensure_chat_session(session_id)

        async def events():
            try:
                async for event in ctx.chat_stream(
                    message,
                    skill=payload.get("skill"),
                    session_id=session_id,
                ):
                    encoded = json.dumps(
                        jsonable_encoder(event),
                        ensure_ascii=False,
                    )
                    yield f"data: {encoded}\n\n"
            except ConfigurationException as exc:
                encoded = json.dumps(
                    {
                        "type": "error",
                        "error": _configuration_error_detail(exc),
                    },
                    ensure_ascii=False,
                )
                yield f"data: {encoded}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @router.get("/chat/history")
    async def chat_history(
        session_id: Optional[str] = None,
        ctx=Depends(get_scoped_ctx),
    ):
        """Return the host-persisted transcript for one PawApp chat session.

        The route deliberately reads the same session state used by
        ``chat``/``chat_stream`` instead of introducing app-owned transcript
        storage. The selected ``agent_id`` is already resolved by ``get_ctx``
        from the standard query parameter.
        """
        effective_session_id = _resolve_app_session_id(ctx, session_id)
        if hasattr(ctx, "ensure_chat_session"):
            await ctx.ensure_chat_session(effective_session_id)
        history = await ctx.get_session_history(effective_session_id)
        # PawApps receive the user-visible transcript and structured tool
        # activity, never model-internal reasoning blocks.
        messages = [
            message
            for message in history
            if message.get("type") != "reasoning"
        ]
        return {
            "session_id": effective_session_id,
            "messages": messages,
        }

    @router.get("/chat/sessions")
    async def chat_sessions(ctx=Depends(get_scoped_ctx)):
        return {"sessions": await ctx.list_chat_sessions()}

    @router.post("/chat/sessions")
    async def create_chat_session(
        request: _ChatSessionCreate,
        ctx=Depends(get_scoped_ctx),
    ):
        return await ctx.create_chat_session(name=request.name)

    @router.patch("/chat/sessions/{chat_id}")
    async def rename_chat_session(
        chat_id: str,
        request: _ChatSessionUpdate,
        ctx=Depends(get_scoped_ctx),
    ):
        try:
            result = await ctx.rename_chat_session(chat_id, name=request.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Chat session not found",
            )
        return result

    @router.post("/chat/sessions/{chat_id}/archive")
    async def archive_chat_session(chat_id: str, ctx=Depends(get_scoped_ctx)):
        result = await ctx.archive_chat_session(chat_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Chat session not found",
            )
        return result

    @router.post("/chat/sessions/{chat_id}/pin")
    async def pin_chat_session(
        chat_id: str,
        request: _ChatSessionPin,
        ctx=Depends(get_scoped_ctx),
    ):
        result = await ctx.pin_chat_session(chat_id, pinned=request.pinned)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Chat session not found",
            )
        return result

    @router.delete("/chat/sessions/{chat_id}")
    async def delete_chat_session(chat_id: str, ctx=Depends(get_scoped_ctx)):
        deleted = await ctx.delete_chat_session(chat_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Chat session not found",
            )
        return {"ok": True}

    @router.get("/storage")
    async def storage_keys(ctx=Depends(get_scoped_ctx)):
        return {"keys": await ctx.storage.keys()}

    @router.get("/storage/{key}")
    async def storage_get(key: str, ctx=Depends(get_scoped_ctx)):
        return {"value": await ctx.storage.get(key)}

    @router.put("/storage/{key}")
    async def storage_set(
        key: str,
        request: Request,
        ctx=Depends(get_scoped_ctx),
    ):
        payload = await request.json()
        await ctx.storage.set(key, payload.get("value"))
        return {"ok": True}

    @router.delete("/storage/{key}")
    async def storage_delete(key: str, ctx=Depends(get_scoped_ctx)):
        await ctx.storage.delete(key)
        return {"ok": True}

    @router.post("/toast")
    async def toast(request: Request, ctx=Depends(get_scoped_ctx)):
        payload = await request.json()
        await ctx.toast(
            str(payload.get("message") or ""),
            kind=str(payload.get("kind") or "info"),
        )
        return {"ok": True}

    @router.post("/notify")
    async def notify(request: Request, ctx=Depends(get_scoped_ctx)):
        payload = await request.json()
        await ctx.notify(
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
        )
        return {"ok": True}

    return router


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
        # Preserve legacy IDs for apps that only use their existing custom
        # routes. The stricter scoped contract is validated when an app opts
        # into the standard capabilities below.
        self.app_id = app_id
        self._plugin_api: Any = None  # set by PluginLoader via .register(api)

        # Internal router for decorator-mode routes
        self._router = APIRouter()
        self._capability_router = _build_capability_router()
        self._standard_capabilities_enabled = False

        # Buffered registrations (applied when .register(api) is called)
        self._tools: List[dict] = []
        self._commands: List[dict] = []
        self._hooks: List[dict] = []
        self._routers: List[APIRouter] = []
        self._lifecycle: dict = {}
        self._skill_providers: List[dict] = []
        self._prompt_sections: List[dict] = []
        self._workspace_hooks: List[dict] = []
        self._runtime_hooks: List[Any] = []
        self._services: List[ManagedService] = []
        self._agent_profiles: List[ManagedAgentProfile] = []
        self.dependencies = DependencyRegistry(lambda: self.app_id)
        self._dependency_agent_tools_enabled = False

    def enable_standard_capabilities(self) -> PawApp:
        """Opt into namespaced chat, storage, toast, and notify routes.

        Explicit opt-in keeps existing PawApps unchanged and reserves strict
        app ID validation for apps using the new app-scoped frontend contract.
        """
        normalized_app_id = self.app_id.strip()
        if not _APP_ID_PATTERN.fullmatch(normalized_app_id):
            raise ValueError(
                "Standard PawApp capabilities require a lowercase "
                f"kebab-case app id: {self.app_id}",
            )
        self.app_id = normalized_app_id
        self._standard_capabilities_enabled = True
        return self

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
        tool_type: str = "network",
        target_param: str = "",
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
                    "tool_type": tool_type,
                    "target_param": target_param,
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

    # ─── Agent and workspace integration ───────────────────────────

    def skill_provider(
        self,
        skills_dir: Path | str,
        *,
        enabled_by_default: bool = True,
        channels: Optional[List[str]] = None,
    ) -> None:
        """Expose a directory of skills through the PawApp SDK."""
        self._skill_providers.append(
            {
                "skills_dir": Path(skills_dir),
                "enabled_by_default": enabled_by_default,
                "channels": channels or ["all"],
            },
        )

    def prompt_section(
        self,
        name: str,
        content: str | Callable,
        *,
        after: str = "workspace",
        priority: int = 100,
        condition: Optional[Callable] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """Add an app-owned section to the host agent's system prompt."""
        provider = content if callable(content) else lambda _agent: content
        self._prompt_sections.append(
            {
                "name": name,
                "after": after,
                "provider": provider,
                "priority": priority,
                "condition": condition,
                "agent_id": agent_id,
            },
        )

    def on_workspace_created(
        self,
        func: Optional[Callable] = None,
        *,
        priority: int = 100,
    ):
        """Register a callback for existing host workspace lifecycle."""

        def decorator(callback: Callable) -> Callable:
            self._workspace_hooks.append(
                {"func": callback, "priority": priority},
            )
            return callback

        return decorator(func) if func is not None else decorator

    def runtime_hook(self, hook: Any) -> Any:
        """Register a runtime hook through PawApp rather than PluginApi."""
        self._runtime_hooks.append(hook)
        return hook

    def agent_profile(
        self,
        agent_id: str,
        *,
        name: str,
        description: str = "",
        persona_dir: Path | str | None = None,
        language: str | None = None,
        plan_enabled: bool = True,
        pinned: bool = True,
    ) -> ManagedAgentProfile:
        """Declare a stable agent identity owned by this PawApp.

        The SDK creates the profile during host startup and schedules it via
        the normal workspace manager. Uninstall detaches the profile but
        preserves conversations, artifacts, and other workspace data.
        """
        profile = ManagedAgentProfile(
            ManagedAgentProfileSpec(
                app_id=self.app_id,
                agent_id=agent_id,
                name=name,
                description=description,
                persona_dir=Path(persona_dir) if persona_dir else None,
                language=language,
                plan_enabled=plan_enabled,
                pinned=pinned,
            ),
        )
        self._agent_profiles.append(profile)
        return profile

    def managed_service(
        self,
        name: str,
        *,
        command: Sequence[str],
        health_path: str = "/health",
        host: str = "127.0.0.1",
        startup_timeout: float = 30.0,
        shutdown_timeout: float = 10.0,
        cwd: Path | str | None = None,
        env: Optional[Mapping[str, str]] = None,
        external_url_env: str | None = None,
        mode_env: str | None = None,
        on_before_start: Optional[Callable[[], Awaitable[None]]] = None,
        display_name: str | None = None,
        capabilities: Sequence[str] = (),
        required: bool = True,
        expose_dependency: bool = True,
        runtime_remediation: str | None = None,
    ) -> ManagedService:
        """Declare a process managed with the PawApp lifecycle."""
        service = ManagedService(
            ManagedServiceSpec(
                name=name,
                command=tuple(command),
                health_path=health_path,
                host=host,
                startup_timeout=startup_timeout,
                shutdown_timeout=shutdown_timeout,
                cwd=Path(cwd) if cwd else None,
                env=dict(env or {}),
                external_url_env=external_url_env,
                mode_env=mode_env,
                on_before_start=on_before_start,
            ),
        )
        self._services.append(service)
        if expose_dependency:

            async def probe_service() -> DependencyHealth:
                ready = await service.check_health()
                if ready:
                    return DependencyHealth(
                        health="healthy",
                        lifecycle="running",
                        message="Ready",
                    )
                if not service.runtime_available():
                    # Starting would only spawn a doomed process; report the
                    # missing runtime with app-provided remediation instead.
                    return DependencyHealth(
                        health="unavailable",
                        lifecycle="stopped",
                        error_code="RUNTIME_MISSING",
                        message="Service runtime is not provisioned",
                        remediation=runtime_remediation
                        or (
                            "Provision the app runtime or attach an "
                            "external endpoint"
                        ),
                    )
                return DependencyHealth(
                    health="unavailable",
                    lifecycle="stopped",
                    message="Service is not running",
                    error_code="SERVICE_STOPPED",
                    remediation="Start the managed service",
                )

            self.dependency(
                name,
                display_name=display_name or name.replace("-", " ").title(),
                ownership="host_managed",
                capabilities=capabilities,
                required=required,
                probe=DependencyProbe(
                    callback=probe_service,
                    timeout_seconds=min(startup_timeout, 3.0),
                    cache_seconds=5.0,
                ),
                lifecycle=DependencyLifecycle(
                    start=service.start,
                    stop=service.stop,
                    restart=service.restart,
                    action_timeout_seconds=startup_timeout + shutdown_timeout,
                    readiness_timeout_seconds=startup_timeout,
                ),
            )
        return service

    def dependency(
        self,
        dependency_id: str,
        *,
        display_name: str | None = None,
        ownership: str = "external",
        capabilities: Sequence[str] = (),
        required: bool = True,
        probe: DependencyProbe,
        lifecycle: DependencyLifecycle | None = None,
        replace: bool = False,
    ) -> DependencySpec:
        """Declare a sanitized health probe and optional typed lifecycle."""
        return self.dependencies.register(
            dependency_id,
            display_name=display_name,
            ownership=ownership,
            capabilities=capabilities,
            required=required,
            probe=probe,
            lifecycle=lifecycle,
            replace=replace,
        )

    def remove_dependency(self, dependency_id: str) -> bool:
        """Drop one dependency so runtime catalogs can reconcile removals."""
        return self.dependencies.unregister(dependency_id)

    def enable_dependency_agent_tools(self) -> PawApp:
        """Opt into app-scoped status and lifecycle tools for the agent."""
        self._dependency_agent_tools_enabled = True
        return self

    # ─── Plugin registration (called by PluginLoader) ───────────────

    def register(self, api: Any) -> None:  # pylint: disable=R0912
        """Called by PluginLoader when the plugin is loaded.

        ``api`` is a ``PluginApi`` instance. We apply all buffered
        registrations now.
        """
        self._plugin_api = api

        # Create app_id injector dependency
        app_id_injector = Depends(_make_app_id_injector(self.app_id))

        # PluginRegistry owns one prefix per plugin. Aggregate every PawApp
        # router so standard capabilities and app routes share one atomic
        # registration instead of competing for the same prefix.
        prefix = f"/{self.app_id}" if self.app_id else ""
        aggregate_router = APIRouter(dependencies=[app_id_injector])
        if self._standard_capabilities_enabled:
            aggregate_router.include_router(self._capability_router)

        if self._router.routes:
            aggregate_router.include_router(self._router)

        for router in self._routers:
            aggregate_router.include_router(router)

        if len(self.dependencies):
            aggregate_router.include_router(self.dependencies.router())

        if aggregate_router.routes:
            api.register_http_router(
                aggregate_router,
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
                tool_type=tool_info.get("tool_type", "network"),
                target_param=tool_info.get("target_param", ""),
            )

        if self._dependency_agent_tools_enabled and len(self.dependencies):

            async def dependency_status(
                dependency_id: str = "",
                force: bool = False,
            ) -> Any:
                if dependency_id:
                    return await self.dependencies.get(
                        dependency_id,
                        force=force,
                    )
                return await self.dependencies.snapshot(force=force)

            async def dependency_action(
                dependency_id: str,
                action: str,
            ) -> Any:
                return await self.dependencies.action(dependency_id, action)

            api.register_tool(
                tool_name=f"{self.app_id}_dependency_status",
                tool_func=dependency_status,
                description=(
                    f"Inspect structured dependency and capability health "
                    f"for {self.name}."
                ),
                icon="🩺",
                enabled=True,
                tool_type="network",
                target_param="dependency_id",
            )
            api.register_tool(
                tool_name=f"{self.app_id}_dependency_action",
                tool_func=dependency_action,
                description=(
                    "Run a pre-registered dependency action such as "
                    "check, start, stop, or restart. Arbitrary commands "
                    "are not accepted."
                ),
                icon="⚙️",
                enabled=True,
                tool_type="internal",
                target_param="dependency_id",
            )

        for provider in self._skill_providers:
            api.register_skill_provider(**provider)

        for section in self._prompt_sections:
            api.register_prompt_section(**section)

        for index, workspace_hook in enumerate(self._workspace_hooks):
            api.register_workspace_created_hook(
                hook_name=f"pawapp_{self.app_id}_workspace_{index}",
                callback=workspace_hook["func"],
                priority=workspace_hook["priority"],
            )

        for runtime_hook in self._runtime_hooks:
            api.register_runtime_hook(runtime_hook)

        for profile in self._agent_profiles:

            async def ensure_profile(
                selected_profile: ManagedAgentProfile = profile,
            ) -> None:
                # Profile provisioning copies files and rewrites config on
                # disk; keep that off the event loop so a hot install never
                # stalls concurrent requests.
                await asyncio.to_thread(selected_profile.ensure)
                registry = getattr(api, "_registry", None)
                manager = (
                    registry.get_workspace_manager() if registry else None
                )
                if manager is not None:
                    manager.schedule_agent_startup(
                        selected_profile.spec.agent_id,
                    )

            async def detach_profile(
                selected_profile: ManagedAgentProfile = profile,
                **_kwargs,
            ) -> None:
                await asyncio.to_thread(selected_profile.detach)

            api.register_startup_hook(
                hook_name=(
                    f"pawapp_{self.app_id}_agent_{profile.spec.agent_id}"
                ),
                callback=ensure_profile,
                priority=35,
            )
            api.register_uninstall_hook(
                hook_name=(
                    f"pawapp_{self.app_id}_agent_{profile.spec.agent_id}"
                ),
                callback=detach_profile,
                priority=110,
            )

        for service in self._services:
            api.register_startup_hook(
                hook_name=f"pawapp_{self.app_id}_service_{service.spec.name}",
                callback=service.start,
                priority=70,
            )
            api.register_shutdown_hook(
                hook_name=f"pawapp_{self.app_id}_service_{service.spec.name}",
                callback=service.stop,
                priority=130,
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
            len(aggregate_router.routes),
            len(self._tools),
        )
