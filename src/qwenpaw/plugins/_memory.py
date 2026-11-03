# -*- coding: utf-8 -*-
"""Adapt a public backend to the existing memory registry and shared worker."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

import inspect
import uuid
from contextlib import asynccontextmanager
from dataclasses import fields, replace

from .errors import SDKError, StaleContextError
from .memory import MemoryContext
from .resources import Registration
from .storage import PluginConfig
from .tools import ToolResult


# Keep the ownership state machine in one scope.
# pylint: disable-next=too-many-statements
def register(plugin, spec):
    import jsonschema
    from ..agents.memory.base_memory_manager import (
        AutoMemorySearchOptions,
        BaseMemoryManager,
        memory_registry,
    )
    from ._messages import _to_block, from_host

    jsonschema.Draft202012Validator.check_schema(spec.config_schema)
    admitted = True

    class Adapter(BaseMemoryManager):
        def __init__(self, *, context):
            plugin._guard()
            jsonschema.validate(
                dict(context.backend_config),
                spec.config_schema,
            )
            super().__init__(context=context)
            self._backend = None
            self._sdk_scope = None
            self._sdk_public = None
            self._sdk_closed = False

        @asynccontextmanager
        async def _invoke(self, *, closing=False):
            if self._sdk_closed or (not admitted and not closing):
                raise StaleContextError(
                    f"Memory backend {spec.id!r} has been released",
                )
            from ..config.context import get_current_session_id

            async with plugin._invocation(
                workspace_id=self.agent_id,
                session_id=get_current_session_id() or "",
            ) as base:
                public = MemoryContext(
                    **{
                        field.name: getattr(base, field.name)
                        for field in fields(base)
                    },
                    backend_id=spec.id,
                    language=self.context.language,
                )
                yield replace(
                    public,
                    config=PluginConfig(
                        dict(self.context.backend_config),
                        {"secrets": spec.secrets},
                    ),
                )

        async def start(self):
            if self._backend is not None:
                return
            async with self._invoke() as public:
                self._sdk_scope = plugin.resources.child(
                    workspace_id=self.agent_id,
                    instance_id=uuid.uuid4().hex,
                )
                self._sdk_public = replace(public, resources=self._sdk_scope)
                # Factory construction is deliberately outside registration and
                # can use ordinary Python objects without exposing host state.
                from ..utils.io_utils import run_sync_io

                self._backend = await run_sync_io(spec.create)
                if inspect.isawaitable(self._backend):
                    self._backend = await self._backend
                for method in ("start", "search", "remember", "close"):
                    if not callable(getattr(self._backend, method, None)):
                        raise SDKError(f"Memory backend requires {method}()")
                await plugin._call(self._backend.start, self._sdk_public)

        async def memory_search(self, query, max_results=5, **kwargs):
            from agentscope.tool import ToolChunk
            from agentscope.message import ToolResultState

            async with self._invoke() as public:
                result = await plugin._call(
                    self._backend.search,
                    public,
                    query,
                    max_results,
                )
                if not isinstance(result, ToolResult) or any(
                    block.type
                    not in {"text", "image", "audio", "video", "file"}
                    for block in result.content
                ):
                    raise SDKError(
                        "Memory search must return ToolResult with "
                        "text/attachment blocks",
                    )
                return ToolChunk(
                    content=[_to_block(block) for block in result.content],
                    state=(
                        ToolResultState.ERROR
                        if result.is_error
                        else ToolResultState.SUCCESS
                    ),
                    is_last=True,
                    metadata=result.metadata,
                )

        async def auto_memory(self, messages, **kwargs):
            async with self._invoke() as public:
                result = await plugin._call(
                    self._backend.remember,
                    public,
                    tuple(from_host(message) for message in messages),
                )
                if not isinstance(result, str):
                    raise SDKError("Memory remember must return text")
                return result

        def get_memory_prompt(self):
            plugin._guard()
            return spec.prompt

        def get_auto_memory_interval(self):
            return spec.auto_memory_interval

        async def get_auto_memory_search_options(self):
            return (
                None
                if spec.auto_search_max_results is None
                else AutoMemorySearchOptions(
                    max_results=spec.auto_search_max_results,
                )
            )

        async def _close_backend(self):
            if self._sdk_closed:
                return True
            if self._backend is not None:
                async with self._invoke(closing=True) as public:
                    result = await plugin._call(
                        self._backend.close,
                        replace(public, resources=self._sdk_scope),
                    )
                    if result is not True:
                        return False
            if self._sdk_scope is not None:
                await self._sdk_scope.close()
                plugin.resources._handles[:] = [
                    handle
                    for handle in plugin.resources._handles
                    if getattr(handle._release, "__self__", None)
                    is not self._sdk_scope
                ]
            self._sdk_closed = True
            return True

    plugin._guard()
    plugin._api.register_memory_backend(
        backend_id=spec.id,
        factory=Adapter,
        label=spec.label,
    )

    async def release():
        nonlocal admitted
        # Selection/live-instance leases are checked before denying an active
        # backend's service operations, so a rejected revoke stays usable.
        if (
            plugin._loader.lifecycle.get_instance(plugin.plugin_id)
            is plugin._instance
            and getattr(plugin._instance, "sdk_context", None) is plugin
        ):
            manager = plugin._api._registry._workspace_manager
            workspaces = getattr(
                manager,
                "agents",
                getattr(manager, "workspaces", {}),
            )
            if any(
                getattr(
                    getattr(
                        getattr(workspace, "_config", None),
                        "running",
                        None,
                    ),
                    "memory_manager_backend",
                    None,
                )
                == spec.id
                for workspace in workspaces.values()
            ):
                raise SDKError("Memory backend is selected by a workspace")
            memory_registry.unregister(spec.id, expected_factory=Adapter)
            admitted = False

    return Registration(
        release,
        owner=plugin.resources.owner,
        description=f"memory:{spec.id}",
    )
