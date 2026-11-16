# -*- coding: utf-8 -*-
"""Host routing; no plugin may bypass permission checks or fall back on error."""

import asyncio
import inspect
import math
import re

from .errors import SDKError
from .shell import ShellRequest, ShellResult


class ShellRouter:
    def __init__(self):
        self.backends = {}
        self.selected = {}

    async def execute(self, identity, request, sandbox_config):
        from agentscope.message import TextBlock, ToolResultState
        from agentscope.tool import ToolChunk

        def error(message):
            return ToolChunk(
                is_last=True,
                state=ToolResultState.ERROR,
                content=[TextBlock(type="text", text=message)],
            )

        if identity is None or not all(
            (
                identity.workspace_id,
                identity.session_id,
                identity.user_id,
                identity.channel,
            ),
        ):
            # Unbound direct calls cannot select someone else's connection.
            return None
        try:
            matches = []
            for key, (plugin, spec) in tuple(self.backends.items()):
                with plugin._instance.activity.sync_invocation():
                    plugin._guard()
                    matched = spec.matches(identity)
                    if type(matched) is not bool:
                        if inspect.iscoroutine(matched):
                            matched.close()
                        raise SDKError(
                            "Shell matches must return bool synchronously",
                        )
                    if matched:
                        matches.append((key, plugin, spec))
            if len(matches) > 1:
                raise SDKError(
                    "Multiple shell backends match; deselect the extra target",
                )
            if not matches:
                previous = self.selected.get(identity)
                if previous is not None:
                    previous_key, previous_owner = previous
                    current = self.backends.get(previous_key)
                    if (
                        current is None
                        or current[0].resources.owner != previous_owner
                    ):
                        raise SDKError(
                            "Selected shell backend is unavailable; "
                            "local execution refused",
                        )
                self.selected.pop(identity, None)
                return None
            key, plugin, spec = matches[0]
            if identity not in self.selected and len(self.selected) >= 4096:
                raise SDKError(
                    "Shell selection capacity reached; local execution refused",
                )
            self.selected[identity] = (key, plugin.resources.owner)
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
                call.workspace_ops.directory
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
            return error(
                f"Shell backend failed; local execution refused: {type(exc).__name__}: {exc}",
            )


def router(registry):
    if not hasattr(registry, "_sdk_shell_router"):
        registry._sdk_shell_router = ShellRouter()
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
    from .context import RequestContext
    from .registry import PluginRegistry

    context = tool._qp_request_context
    identity = RequestContext(
        context.get("agent_id", "") or getattr(tool, "_qp_agent_id", "") or "",
        context.get("session_id", ""),
        context.get("channel", ""),
        context.get("user_id", ""),
    )
    owned = getattr(PluginRegistry(), "_sdk_shell_router", None)
    if owned is not None:
        result = await owned.execute(
            identity,
            ShellRequest(
                arguments.get("command", ""),
                str(arguments["cwd"])
                if arguments.get("cwd") is not None
                else None,
                arguments.get("timeout", 60.0),
            ),
            arguments.get("sandbox_config"),
        )
        if result is not None:
            return result
    return await FunctionTool.call(tool, **arguments)
