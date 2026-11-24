# -*- coding: utf-8 -*-
"""Host routing; no plugin may bypass permission checks or fall back on error."""

import asyncio
import inspect
import math
import re

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ..agents.tools.shell import resolve_shell_command_timeout
from .context import RequestContext
from ._identity import control_context
from .errors import SDKAccessError, SDKError
from .shell import ShellRequest, ShellResult


def _bound(identity):
    return all(
        (
            identity.workspace_id,
            identity.session_id,
            identity.user_id,
            identity.channel,
        ),
    )


_UNAVAILABLE = (
    "Selected shell backend is unavailable; use /shell-local to switch back"
)


async def _chat_manager(registry, workspace_id):
    workspace = registry._stop_workspaces.get(workspace_id)
    manager = registry.get_workspace_manager()
    if workspace is None and manager is not None:
        workspace = await manager.get_agent(workspace_id)
    return workspace.chat_manager if workspace is not None else None


async def select_backend(call, name):
    from .apps import AppContext

    control = control_context.get()
    if isinstance(call, AppContext):
        workspace, chat = await call._services.selected_conversation()
        identity = RequestContext(
            call.workspace_id,
            chat.session_id,
            chat.channel,
            chat.user_id,
        )
        chats = workspace.chat_manager
    elif control is not None and control[0] is call and _bound(call.identity):
        identity = call.identity
        chats = control[1].workspace.chat_manager
    else:
        raise SDKAccessError(
            "Select a shell backend from an app or control command",
        )
    await call.workspace_ops._directory_async()
    plugin = call._plugin
    if plugin is None:
        raise SDKAccessError("Shell selection requires a host-owned context")
    owner = plugin.plugin_id
    key = None
    if name is not None:
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            name,
        ):
            raise SDKError("Invalid shell backend name")
        key = f"{owner}:{name}"
        entry = router(plugin._loader.registry).backends.get(key)
        if entry is None or entry[0] is not plugin:
            raise SDKError("Shell backend is not registered by this plugin")
    if not await chats.set_shell_backend(
        identity.session_id,
        identity.user_id,
        identity.channel,
        key,
        owner=owner,
    ):
        raise SDKAccessError(
            "Chat unavailable or selected backend belongs to another plugin",
        )


class ShellRouter:
    def __init__(self, registry):
        self.registry = registry
        self.backends = {}

    async def execute(
        self,
        identity: RequestContext,
        request: ShellRequest,
        sandbox_config: object,
    ) -> ToolChunk | None:
        if not _bound(identity):
            # Unbound direct calls cannot select someone else's connection.
            return None
        try:
            chats = await _chat_manager(self.registry, identity.workspace_id)
            if chats is None:
                if self.backends:
                    raise SDKError("Shell selection state is unavailable")
                return None
            key = await chats.shell_backend_for(
                identity.session_id,
                identity.user_id,
                identity.channel,
            )
            if key is None:
                return None
            backend = self.backends.get(key)
            if backend is None:
                raise SDKError(_UNAVAILABLE)
            plugin, spec = backend
            if sandbox_config is not None:
                raise SDKError(
                    "Selected shell backend cannot enforce the required local sandbox policy",
                )
            if not math.isfinite(request.timeout) or request.timeout <= 0:
                raise SDKError("Shell timeout must be finite and positive")
            async with plugin._invocation(
                workspace_id=identity.workspace_id,
                session_id=identity.session_id,
                identity=identity,
            ) as call:
                await call.workspace_ops._directory_async()
                matched = spec.matches(identity)
                if type(matched) is not bool:
                    if inspect.iscoroutine(matched):
                        matched.close()
                    raise SDKError(
                        "Shell matches must return bool synchronously",
                    )
                if not matched:
                    raise SDKError(_UNAVAILABLE)
                from ..tool_calls import cancellable_wait

                result = await cancellable_wait(
                    call.resources.task(
                        spec.execute(call, request),
                        "shell execution",
                    ),
                    fallback_secs=request.timeout,
                    as_kill_deadline=True,
                )
                if (
                    not isinstance(result, ShellResult)
                    or type(result.exit_code) is not int
                    or not isinstance(result.stdout, str)
                    or not isinstance(result.stderr, str)
                ):
                    raise SDKError("Shell backend must return ShellResult")
                text = result.stdout[: 1024 * 1024]
                if result.stderr:
                    text += "\n[stderr]\n" + result.stderr[: 1024 * 1024]
                if result.exit_code:
                    text = (
                        f"Command failed with exit code {result.exit_code}.\n"
                        + text
                    )
                return ToolChunk(
                    is_last=True,
                    state=(
                        ToolResultState.SUCCESS
                        if result.exit_code == 0
                        else ToolResultState.ERROR
                    ),
                    content=[
                        TextBlock(
                            type="text",
                            text=text
                            or "Command executed successfully (no output).",
                        ),
                    ],
                    metadata={
                        "shell_backend": key,
                        "exit_code": result.exit_code,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Shell backend failed; local execution refused: {type(exc).__name__}: {exc}",
                    ),
                ],
            )


def router(registry):
    if not hasattr(registry, "_sdk_shell_router"):
        registry._sdk_shell_router = ShellRouter(registry)
    return registry._sdk_shell_router


def register(plugin, spec):
    plugin._guard()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spec.name) or not callable(
        spec.matches,
    ):
        raise SDKError("Shell backend requires a name and identity predicate")
    if not inspect.iscoroutinefunction(spec.execute):
        raise SDKError("Shell backend execute must be async")
    owned = router(plugin._loader.registry)
    key = plugin.plugin_id + ":" + spec.name
    if key in owned.backends:
        raise SDKError("Shell backend already registered: " + key)
    entry = (plugin, spec)
    owned.backends[key] = entry

    async def release():
        if owned.backends.get(key) is entry:
            del owned.backends[key]

    from .resources import Registration

    handle = Registration(
        release,
        owner=plugin.resources.owner,
        description="shell backend:" + key,
        _bounded=False,
    )
    plugin._instance.record_runtime(handle.description, handle.close)
    return handle


async def function_call(tool, **arguments):
    """Execution hook downstream of the runtime's normal permission decision."""
    from agentscope.tool import FunctionTool
    from .registry import PluginRegistry

    context = tool._qp_request_context
    identity = RequestContext(
        context.get("agent_id", "") or getattr(tool, "_qp_agent_id", "") or "",
        context.get("session_id", ""),
        context.get("channel", ""),
        context.get("user_id", ""),
    )
    registry = PluginRegistry()
    arguments["timeout"] = resolve_shell_command_timeout(
        arguments.get("timeout", 60.0),
    )
    result = await router(registry).execute(
        identity,
        ShellRequest(
            arguments.get("command", ""),
            (
                str(arguments["cwd"])
                if arguments.get("cwd") is not None
                else None
            ),
            arguments.get("timeout", 60.0),
        ),
        arguments.get("sandbox_config"),
    )
    if result is not None:
        return result
    return await FunctionTool.call(tool, **arguments)
