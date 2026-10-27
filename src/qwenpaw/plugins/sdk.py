# -*- coding: utf-8 -*-
"""Opt-in public context and internal bridge to the existing PluginApi."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import fields, replace
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Protocol, Callable, Awaitable, TYPE_CHECKING

from .errors import SDKError, StaleContextError, ToolInputError, ResourceError
from .resources import Registration, ResourceOwner, ResourceScope
from .storage import MediaStore, PluginConfig, PluginStorage
from .tools import ToolContext, ToolEvent, ToolResult, ToolSpec
from .channels import ChannelSpec
from .commands import CommandSpec
from .hooks import HookSpec
from .prompts import PromptSpec
from .modes import ModeSpec
from .skills import SkillSpec
from .markets import MarketSpec
from .providers import ProviderSpec
from .memory import MemorySpec
from .events import EventSubscription
from .apps import PawApp

if TYPE_CHECKING:
    from .logging import PluginLogger


_activation_owners = ContextVar("sdk_activation_owners", default=frozenset())
# An App run owns only the SDK stream producers spawned in its call chain.
_stream_tasks = ContextVar("sdk_run_stream_tasks", default=None)


class _RunStreams:
    def __init__(self):
        self.tasks = set()
        self.scopes = {}
        self.streams = {}
        self.closing = False

    def retain(self, stream):
        async def close():
            # Host-created anext tasks may still be finishing cancellation.
            # The observer supplies native async generators only.
            while stream.ag_running:
                await asyncio.sleep(0.01)
            await stream.aclose()
            self.streams.pop(stream, None)

        self.streams.setdefault(stream, close)
        if self.closing:
            # The factory already created it: retain cleanup even when
            # rejecting
            # late work, rather than losing the returned generator to GC.
            raise StaleContextError("The model run is closing")

    def closers(self):
        yield from tuple(self.streams.values())
        # An outer stream can still need its child scopes while closing.
        if not self.streams:
            yield from tuple(self.scopes.values())


class Plugin(Protocol):
    def register(self, context: PluginContext) -> None:
        """Declare contributions and activation callbacks."""


class PluginContext:  # pylint: disable=protected-access
    """Finite plugin capabilities; internal host objects are never returned."""

    def __init__(self, api):
        from ..constant import DEFAULT_MEDIA_DIR, WORKING_DIR

        self._api = api
        self._instance = api._instance
        self._loader = api._loader
        self.plugin_id = api.plugin_id
        self.generation = self._instance.generation
        self._activating = False
        self._tools = {}
        self.config = PluginConfig(api.config, api.manifest.get("sdk") or {})
        self.storage = PluginStorage(
            WORKING_DIR / "plugin-data" / self.plugin_id,
            self._storage_guard,
            _admission=self._storage_admission,
        )
        self.media = MediaStore(
            PluginStorage(
                DEFAULT_MEDIA_DIR / "plugins" / self.plugin_id,
                self._storage_guard,
                _admission=self._storage_admission,
            ),
            "/api/files/preview/"
            + str(DEFAULT_MEDIA_DIR / "plugins" / self.plugin_id),
        )
        self.resources = ResourceScope(
            ResourceOwner(
                self.plugin_id,
                self.generation,
                instance_id=uuid.uuid4().hex,
            ),
            self._resource_guard,
        )
        self._instance.record_runtime(
            "sdk:resources",
            self.resources.close,
            kind="custody",
        )

    @property
    def logger(self) -> "PluginLogger":
        from .logging import PluginLogger

        return PluginLogger(self)

    def _guard(self):
        from .lifecycle import PluginState

        if (
            self._loader.lifecycle.get_instance(self.plugin_id)
            is not self._instance
            or getattr(self._instance, "sdk_context", None) is not self
            or self._instance.state is not PluginState.ACTIVE
        ):
            raise StaleContextError(
                f"Plugin {self.plugin_id!r} generation {self.generation} "
                "is no longer active",
            )

    def _storage_guard(self):
        # Retained failed/stopping generations may persist cleanup state, but
        # replacement immediately revokes writes even if an old handle
        # survives.
        from .lifecycle import PluginState

        if (
            self._loader.lifecycle.get_instance(self.plugin_id)
            is not self._instance
            or getattr(self._instance, "sdk_context", None) is not self
            or self._instance.state is PluginState.DISPOSED
        ):
            raise StaleContextError("Plugin storage owner has been replaced")

    def _resource_guard(self):
        self._guard()
        if not (
            any(owner == id(self) for owner, _ in _activation_owners.get())
            or self._instance.activated
        ):
            raise ResourceError(
                "Create resources in on_activate(), not register()",
            )

    @contextmanager
    def _storage_admission(self):
        from .resources import _storage_cleanup

        self._storage_guard()
        activity = self._instance.activity
        task = asyncio.current_task()
        cleanup = _storage_cleanup.get()
        finishing = (
            cleanup is not None
            and cleanup[1] is task
            and (
                cleanup[0].plugin_id == self.plugin_id
                and cleanup[0].generation == self.generation
            )
        )
        if (
            task in activity.tasks
            or task in activity.cleanup_tasks
            or task is activity.mutator
            or finishing
        ):
            # Only storage may finish an admitted call or its exact release
            # task. This does not reopen model/resource/business admission.
            activity.tasks[task] = activity.tasks.get(task, 0) + 1
            try:
                yield
            finally:
                activity.tasks[task] -= 1
                if not activity.tasks[task]:
                    del activity.tasks[task]
        else:
            with self._admission():
                yield

    @contextmanager
    def _activation(self):
        token = _activation_owners.set(
            _activation_owners.get() | {(id(self), asyncio.current_task())},
        )
        try:
            yield
        finally:
            _activation_owners.reset(token)

    @contextmanager
    def _admission(self, *, cleanup=False):
        activity = self._instance.activity
        task = asyncio.current_task()
        if (id(self), task) not in _activation_owners.get():
            with activity.invocation(cleanup=cleanup):
                yield
            return
        # The real Lifecycle mutation owns activation. Projector startup tasks
        # must be counted without reopening admission to ordinary callbacks.
        activity.tasks[task] = activity.tasks.get(task, 0) + 1
        try:
            yield
        finally:
            activity.tasks[task] -= 1
            if not activity.tasks[task]:
                del activity.tasks[task]

    def on_activate(
        self,
        callback: Callable[[PluginContext], None | Awaitable[None]],
    ) -> Registration:
        self._guard()
        name = f"sdk:activate:{len(self._instance._runtime)}"

        async def activate():
            if handle.closed:
                return
            self._guard()
            with self._activation():
                result = callback(self)
                if inspect.isawaitable(result):
                    await result

        self._api.register_startup_hook(name, activate)

        def release():
            if (
                self._loader.lifecycle.get_instance(self.plugin_id)
                is self._instance
                and getattr(self._instance, "sdk_context", None) is self
            ):
                self._api._drop_hook(name)()

        handle = Registration(
            release,
            owner=self.resources.owner,
            description=name,
        )
        return handle

    @asynccontextmanager
    async def _invocation(
        self,
        *,
        workspace_id: str,
        session_id: str,
        deadline=None,
        cleanup=False,
    ):
        self._guard()
        from ._models import model_deadline

        inherited = model_deadline.get()
        if inherited is not None:
            deadline = (
                inherited if deadline is None else min(deadline, inherited)
            )
        owned = None if cleanup else _stream_tasks.get()
        if owned is not None and owned.closing:
            raise SDKError("The owning app run is closing")
        if not (
            self._instance.activated
            or (id(self), asyncio.current_task()) in _activation_owners.get()
        ):
            raise SDKError("Plugin activation has not completed")
        with self._admission(cleanup=cleanup):
            task = asyncio.current_task()
            scope = self.resources.child(
                workspace_id=workspace_id,
                instance_id=uuid.uuid4().hex,
            )
            storage, media = self.storage, self.media
            if workspace_id:
                import hashlib

                key = hashlib.sha256(workspace_id.encode()).hexdigest()
                storage = PluginStorage(
                    self.storage._root / "workspaces" / key,
                    self._storage_guard,
                    _admission=self._storage_admission,
                )
                media_root = self.media._storage._root / "workspaces" / key
                media = MediaStore(
                    PluginStorage(
                        media_root,
                        self._storage_guard,
                        _admission=self._storage_admission,
                    ),
                    "/api/files/preview/" + str(media_root),
                )
            context = ToolContext(
                self.plugin_id,
                self.generation,
                workspace_id,
                session_id,
                self.config,
                storage,
                media,
                scope,
                deadline=deadline,
                _is_cancelled=lambda: bool(task and task.cancelling()),
                _plugin=self,
            )

            async def close_scope():
                await scope.close()
                self.resources._handles[:] = [
                    handle
                    for handle in self.resources._handles
                    if getattr(handle._release, "__self__", None) is not scope
                ]
                if owned is not None:
                    owned.scopes.pop(scope, None)

            if owned is not None:
                owned.scopes[scope] = close_scope
            try:
                yield context
            finally:
                await close_scope()

    async def _managed_stream(
        self,
        factory,
        label,
        *,
        deadline=None,
        resources=None,
    ):
        """A producer owns the complete stream, including suspended yields."""
        from .custody import stop_task

        queue = asyncio.Queue(maxsize=1)
        resumed = asyncio.Event()

        async def produce():
            stream = factory()
            try:
                async for event in stream:
                    # Some host streams translate cancellation into one final
                    # event. The departed consumer cannot acknowledge it.
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    resumed.clear()
                    await queue.put(event)
                    await resumed.wait()
            finally:
                await stream.aclose()

        owned = _stream_tasks.get()
        if owned is not None and owned.closing:
            raise SDKError("The owning app run is closing")
        producer = (resources or self.resources).task(produce(), label)
        if owned is not None:
            owned.tasks.add(producer)
            producer.add_done_callback(owned.tasks.discard)
        try:
            while True:
                receiver = asyncio.create_task(queue.get())
                try:
                    remaining = (
                        None
                        if deadline is None
                        else max(
                            0,
                            deadline - asyncio.get_running_loop().time(),
                        )
                    )
                    done, _ = await asyncio.wait(
                        {producer, receiver},
                        timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise SDKError(f"{label} exceeded its deadline")
                    if receiver not in done:
                        await producer
                        return
                    self._guard()
                    yield receiver.result()
                    resumed.set()
                finally:
                    if not receiver.done():
                        receiver.cancel()
        finally:
            await stop_task(producer, label)

    def register_channel(self, spec: ChannelSpec) -> Registration:
        from ._channels import register

        return register(self, spec)

    async def _stream_tool(
        self,
        name,
        arguments,
        *,
        workspace_id="",
        session_id="",
    ):
        timeout = self._tools[name][0].timeout
        deadline = (
            None
            if timeout is None
            else asyncio.get_running_loop().time() + timeout
        )
        stream = self._managed_stream(
            lambda: self._produce_tool(
                name,
                arguments,
                workspace_id=workspace_id,
                session_id=session_id,
                deadline=deadline,
            ),
            f"tool:{name}",
            deadline=deadline,
        )
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    # Keep related adapter declarations and lifecycle ordering together.
    # pylint: disable-next=too-many-branches
    async def _produce_tool(
        self,
        name,
        arguments,
        *,
        workspace_id="",
        session_id="",
        deadline=None,
    ):
        import jsonschema

        self._guard()
        spec, handle, _ = self._tools[name]
        if handle.closed:
            raise StaleContextError(f"Tool {name!r} has been released")
        try:
            jsonschema.validate(arguments, spec.input_schema)
        except jsonschema.ValidationError as exc:
            raise ToolInputError(exc.message) from exc
        async with self._invocation(
            workspace_id=workspace_id,
            session_id=session_id,
            deadline=deadline,
        ) as context:
            if spec.config_fields:
                values = dict(self._api.config)
                from ..utils.io_utils import run_sync_io

                settings = (
                    await run_sync_io(
                        self._api._registry.get_tool_config,
                        spec.name,
                        workspace_id,
                    )
                    or {}
                )
                declared_secrets = list(
                    (self._api.manifest.get("sdk") or {}).get("secrets", []),
                )
                for field in spec.config_fields:
                    key = field["name"]
                    if key in settings:
                        values[key] = settings[key]
                    elif "default" in field:
                        values.setdefault(key, field["default"])
                    if field.get("type") == "password":
                        declared_secrets.append(key)
                    if field.get("required") and values.get(key) in (None, ""):
                        raise SDKError(
                            f"Tool {spec.name!r} requires setting {key!r}",
                        )
                context = replace(
                    context,
                    config=PluginConfig(values, {"secrets": declared_secrets}),
                )
            if inspect.iscoroutinefunction(
                spec.handler,
            ) or inspect.isasyncgenfunction(
                spec.handler,
            ):
                result = spec.handler(context, arguments)
            else:
                from ..utils.io_utils import run_sync_io

                result = await run_sync_io(spec.handler, context, arguments)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResult):
                yield ToolEvent("result", result=result)
            elif hasattr(result, "__aiter__"):
                terminal = False
                try:
                    async for event in result:
                        if (
                            not isinstance(event, ToolEvent)
                            or event.kind not in {"delta", "result", "end"}
                            or (
                                event.kind == "result"
                                and not isinstance(event.result, ToolResult)
                            )
                            or terminal
                        ):
                            raise SDKError(
                                "Tool stream must yield ToolEvent values "
                                "before its end event",
                            )
                        terminal = event.kind == "end"
                        if not terminal:
                            yield event
                finally:
                    closer = getattr(result, "aclose", None)
                    if closer:
                        await closer()
            else:
                raise SDKError(
                    "Tool handler must return ToolResult or an "
                    "asynchronous ToolEvent stream",
                )
            yield ToolEvent("end")

    # Keep related adapter declarations and lifecycle ordering together.
    # pylint: disable-next=too-many-statements
    def register_tool(self, spec: ToolSpec, *, _mode="") -> Registration:
        import jsonschema

        self._guard()
        jsonschema.Draft202012Validator.check_schema(spec.input_schema)
        if spec.timeout is not None and spec.timeout <= 0:
            raise SDKError("Tool timeout must be positive or None")
        if not spec.name.isidentifier() or spec.name in self._tools:
            raise SDKError(f"Invalid or duplicate tool name: {spec.name}")
        if spec.config_fields:
            from copy import deepcopy

            if any(
                not isinstance(field.get("name"), str) or not field["name"]
                for field in spec.config_fields
            ):
                raise SDKError("Tool config fields require nonempty names")
            metadata = self._api.manifest.setdefault("meta", {})
            descriptions = metadata.setdefault("tools", [])
            descriptions[:] = [
                entry
                for entry in descriptions
                if entry.get("name") != spec.name
            ]
            descriptions.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "icon": spec.icon,
                    "requires_config": True,
                    "config_fields": deepcopy(list(spec.config_fields)),
                },
            )

        async def invoke(**arguments):
            from copy import deepcopy
            from agentscope.tool import ToolChunk, ToolResponse
            from agentscope.message import ToolResultState
            from ..config.context import get_current_session_id
            from ._workspace import current_workspace_id

            stream = self._stream_tool(
                spec.name,
                arguments,
                workspace_id=current_workspace_id(),
                session_id=get_current_session_id() or "",
            )
            failed = False
            accumulated = ToolResponse()
            author_metadata = {}
            public_blocks = {}
            text_metadata = None
            try:
                async for event in stream:
                    result = event.result or ToolResult(event.content)
                    failed = failed or result.is_error
                    from ._messages import (
                        _to_block,
                        _preview_refs,
                        _tool_metadata,
                        _metadata_refs,
                        _block_key,
                    )

                    if any(
                        block.type
                        not in {"text", "image", "audio", "video", "file"}
                        for block in result.content
                    ):
                        raise SDKError(
                            "Tool results support text "
                            "and attachment blocks only",
                        )
                    blocks = [_to_block(block) for block in result.content]
                    for public, host in zip(result.content, blocks):
                        if host.type == "text":
                            if (
                                text_metadata is not None
                                and text_metadata != public.metadata
                            ):
                                raise SDKError(
                                    "Adjacent tool text blocks must have "
                                    "equal metadata; the host merges their "
                                    "text into one block",
                                )
                            text_metadata = deepcopy(public.metadata)
                        else:
                            text_metadata = None
                    public_blocks.update(
                        (_block_key(host), public)
                        for public, host in zip(result.content, blocks)
                    )
                    author_metadata.update(result.metadata)
                    accumulated.append_chunk(ToolChunk(content=blocks))
                    complete = [
                        public_blocks[_block_key(block)]
                        for block in accumulated.content
                    ]
                    state = ToolResultState.RUNNING
                    if failed:
                        state = ToolResultState.ERROR
                    elif event.kind == "end":
                        state = ToolResultState.SUCCESS
                    yield ToolChunk(
                        content=blocks,
                        state=state,
                        is_last=event.kind == "end",
                        metadata=_tool_metadata(
                            author_metadata
                            if event.kind == "end"
                            else result.metadata,
                            accumulated.content
                            if event.kind == "end"
                            else blocks,
                            event.kind,
                            failed,
                            (
                                _preview_refs(complete, accumulated.content)
                                if event.kind == "end"
                                else _preview_refs(result.content, blocks)
                            ),
                            (
                                _metadata_refs(complete, accumulated.content)
                                if event.kind == "end"
                                else _metadata_refs(result.content, blocks)
                            ),
                        ),
                    )
            finally:
                await stream.aclose()

        invoke.__name__ = spec.name
        invoke.__doc__ = spec.description
        invoke._qwenpaw_sdk_schema = {"properties": {}, **spec.input_schema}
        if _mode:
            from ..runtime.tool_registry import ToolDescriptor

            invoke._tool_descriptor = ToolDescriptor(
                spec.name,
                invoke,
                enabled_by_default=spec.enabled,
                requires_modes=(_mode,),
                async_execution=True,
                description=spec.description,
                owner_plugin_id=self.plugin_id,
            )
        properties = spec.input_schema.get("properties", {})
        required = spec.input_schema.get("required", [])
        types = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        invoke.__signature__ = inspect.Signature(
            [
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=(
                        inspect.Parameter.empty
                        if name in required
                        else schema.get("default")
                    ),
                    annotation=types.get(schema.get("type"), object),
                )
                for name, schema in properties.items()
            ],
        )
        before = len(self._instance._runtime)
        self._api.register_tool(
            spec.name,
            invoke,
            spec.description,
            spec.icon,
            spec.enabled,
            spec.tool_type,
            spec.target_param,
        )
        rows = list(self._instance._runtime[before:])
        hook = next(
            h
            for h in self._api._registry.get_startup_hooks()
            if h.plugin_id == self.plugin_id
            and h.hook_name == f"register_tool_{self.plugin_id}_{spec.name}"
        )
        original_startup = hook.callback

        async def startup():
            known = {id(row) for row in self._instance._runtime}
            try:
                await original_startup()
            finally:
                rows.extend(
                    row
                    for row in self._instance._runtime
                    if id(row) not in known
                )

        hook.callback = startup

        async def release():
            if (
                self._loader.lifecycle.get_instance(self.plugin_id)
                is self._instance
                and getattr(self._instance, "sdk_context", None) is self
            ):
                for row in reversed(rows):
                    if row.teardown:
                        value = row.teardown()
                        if inspect.isawaitable(value):
                            await value

        handle = Registration(
            release,
            owner=self.resources.owner,
            description=f"tool:{spec.name}",
        )
        self._tools[spec.name] = (spec, handle, invoke)
        return handle

    def _register_contribution(
        self,
        register,
        *args,
        **kwargs,
    ) -> Registration:
        self._guard()
        before = len(self._instance._runtime)
        register(*args, **kwargs)
        rows = tuple(self._instance._runtime[before:])

        async def release():
            if (
                self._loader.lifecycle.get_instance(self.plugin_id)
                is not self._instance
                or getattr(self._instance, "sdk_context", None) is not self
            ):
                return
            for row in reversed(rows):
                if row.teardown:
                    result = row.teardown()
                    if inspect.isawaitable(result):
                        await result

        return Registration(
            release,
            owner=self.resources.owner,
            description=rows[-1].desc if rows else "contribution",
        )

    def _with_admission(self, handle, *entries):
        async def release():
            for entry in entries:
                entry._sdk_closed = True
            await handle.close()

        return Registration(
            release,
            owner=self.resources.owner,
            description=handle.description,
            _bounded=False,
        )

    @staticmethod
    async def _call(handler, context, *arguments):
        if inspect.iscoroutinefunction(handler):
            return await handler(context, *arguments)
        from ..utils.io_utils import run_sync_io

        result = await run_sync_io(handler, context, *arguments)
        return await result if inspect.isawaitable(result) else result

    def _command_adapter(self, spec):
        from .commands import CommandContext, CommandResult
        from ._messages import from_host, to_host
        from ._replies import to_reply

        async def handler(runtime, arguments):
            if getattr(handler, "_sdk_closed", False):
                raise StaleContextError(
                    f"Command {spec.name!r} has been released",
                )
            async with self._invocation(
                workspace_id=runtime.agent_id,
                session_id=runtime.session_id,
            ) as base:
                context = CommandContext(
                    **{f.name: getattr(base, f.name) for f in fields(base)},
                    messages=tuple(from_host(m) for m in runtime.input_msgs),
                )
                result = await self._call(spec.handler, context, arguments)
                self._guard()
                if not isinstance(result, CommandResult):
                    raise SDKError("Command handler must return CommandResult")
                if result.action == "reply" and result.message is not None:
                    return to_reply(result.message)
                if result.action == "replace_input":
                    runtime.input_msgs = [
                        to_host(message) for message in result.messages
                    ]
                elif result.action != "continue":
                    raise SDKError(
                        "Command result requires a valid action "
                        "and reply message",
                    )
                return None

        from ..runtime.slash_command_registry import (
            CommandSpec as RuntimeCommand,
        )

        return RuntimeCommand(
            spec.name,
            handler,
            aliases=spec.aliases,
            help_text=spec.help_text,
            owner_plugin_id=self.plugin_id,
        )

    def register_command(self, spec: CommandSpec) -> Registration:
        adapted = self._command_adapter(spec)
        handle = self._register_contribution(
            self._api.register_slash_command,
            adapted.name,
            adapted.handler,
            aliases=adapted.aliases,
            help_text=adapted.help_text,
        )
        return self._with_admission(handle, adapted.handler)

    def _hook_adapter(self, spec):
        from .hooks import HookContext, HookPhase, HookResult
        from ._messages import from_host, to_host
        from ._replies import to_reply
        from ..runtime.hooks import (
            HookBase,
            HookAction,
            HookResult as RuntimeResult,
        )
        from ..runtime.phases import Phase

        context = self
        phase = HookPhase(spec.phase)
        if spec.timeout is not None and spec.timeout <= 0:
            raise SDKError("Hook timeout must be positive or None")

        class Adapter(HookBase):
            def __init__(self):
                self.name, self.phase, self.priority = (
                    spec.name,
                    Phase(phase.value),
                    spec.priority,
                )
                self.before, self.after = spec.before, spec.after

            # Keep related adapter declarations and lifecycle ordering
            # together.
            # pylint: disable-next=too-many-branches
            async def run(self, runtime):
                if getattr(self, "_sdk_closed", False):
                    raise StaleContextError(
                        f"Hook {spec.name!r} has been released",
                    )

                async def invoke():
                    deadline = (
                        None
                        if spec.timeout is None
                        else asyncio.get_running_loop().time() + spec.timeout
                    )
                    async with context._invocation(
                        workspace_id=runtime.agent_id,
                        session_id=runtime.session_id,
                        deadline=deadline,
                    ) as base:
                        public = HookContext(
                            **{
                                f.name: getattr(base, f.name)
                                for f in fields(base)
                            },
                            phase=phase,
                            messages=tuple(
                                from_host(m) for m in runtime.input_msgs
                            ),
                            error=(
                                str(runtime.error)
                                if runtime.error is not None
                                else None
                            ),
                        )
                        return await context._call(spec.handler, public)

                task = context.resources.task(invoke(), f"hook:{spec.name}")
                try:
                    done, _ = await asyncio.wait({task}, timeout=spec.timeout)
                    if not done:
                        raise SDKError(
                            f"Hook {spec.name!r} exceeded its deadline",
                        )
                    result = task.result()
                finally:
                    if not task.done():
                        task.cancel()
                context._guard()
                if not isinstance(result, HookResult):
                    raise SDKError("Hook handler must return HookResult")
                early = {
                    HookPhase.PRE_DISPATCH,
                    HookPhase.POST_DISPATCH,
                    HookPhase.PRE_AGENT_BUILD,
                }
                if result.replace_input is not None and phase not in early:
                    raise SDKError(
                        "Input replacement is not permitted during "
                        f"{phase.value}",
                    )
                if result.injections and phase not in early | {
                    HookPhase.POST_AGENT_BUILD,
                    HookPhase.PRE_EXECUTE,
                }:
                    raise SDKError(
                        "Context injection is not permitted during "
                        f"{phase.value}",
                    )
                if result.action not in {
                    "continue",
                    "reply",
                    "skip_agent",
                } or (result.action == "reply" and result.message is None):
                    raise SDKError(
                        "Hook result requires a valid action "
                        "and reply message",
                    )
                if result.action != "continue" and phase not in early | {
                    HookPhase.PRE_EXECUTE,
                }:
                    raise SDKError(
                        "Control-flow actions are not permitted during "
                        f"{phase.value}",
                    )
                replacement = (
                    None
                    if result.replace_input is None
                    else [to_host(message) for message in result.replace_input]
                )
                reply = (
                    to_reply(result.message)
                    if result.action == "reply"
                    else None
                )
                for injection in result.injections:
                    if not isinstance(
                        injection.content,
                        str,
                    ) or not isinstance(
                        injection.priority,
                        int,
                    ):
                        raise SDKError(
                            "Context injections require text "
                            "and integer priority",
                        )
                # Apply only after validating and converting every requested
                # change.
                if replacement is not None:
                    runtime.input_msgs = replacement
                for injection in result.injections:
                    runtime.inject_context(
                        injection.content,
                        priority=injection.priority,
                        source=context.plugin_id,
                    )
                return RuntimeResult(
                    (
                        HookAction.SHORT_CIRCUIT
                        if reply is not None
                        else HookAction(result.action)
                    ),
                    reply,
                )

        adapter = Adapter()
        adapter.owner_plugin_id = self.plugin_id
        return adapter

    def register_hook(self, spec: HookSpec) -> Registration:
        adapter = self._hook_adapter(spec)
        handle = self._register_contribution(
            self._api.register_runtime_hook,
            adapter,
        )
        return self._with_admission(handle, adapter)

    def register_prompt(self, spec: PromptSpec) -> Registration:
        def provider(_runtime):
            self._guard()
            if getattr(provider, "_sdk_closed", False):
                raise StaleContextError(
                    f"Prompt {spec.name!r} has been released",
                )
            return spec.text

        handle = self._register_contribution(
            self._api.register_prompt_section,
            spec.name,
            "workspace",
            provider,
            priority=spec.priority,
            agent_id=spec.workspace_id,
        )
        return self._with_admission(handle, provider)

    def register_mode(self, spec: ModeSpec) -> Registration:
        from .modes import ModeContext
        from ._messages import from_host
        from ..modes.base import AgentMode, ModeGatedHook
        from ..runtime.prompt_manager import SyncPromptContributor

        self._guard()
        if not spec.name or not callable(spec.is_active):
            raise SDKError(
                "Modes require a name and synchronous is_active predicate",
            )
        context = self
        admitted = True

        def snapshot(runtime):
            if not admitted:
                raise StaleContextError(
                    f"Mode {spec.name!r} has been released",
                )
            return ModeContext(
                context.plugin_id,
                context.generation,
                runtime.agent_id,
                runtime.session_id,
                spec.name,
                tuple(from_host(message) for message in runtime.input_msgs),
                context.config,
            )

        class Adapter(AgentMode):
            name = spec.name

            # Keep the existing adapter callback signature.
            # pylint: disable-next=arguments-renamed
            def is_active(self, runtime):
                context._guard()
                with context._instance.activity.invocation():
                    result = spec.is_active(snapshot(runtime))
                if not isinstance(result, bool):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise SDKError(
                        "Mode is_active must return bool synchronously",
                    )
                return result

            def commands(self):
                return [
                    context._command_adapter(item) for item in spec.commands
                ]

            def hooks(self):
                owner = self
                output = []
                for item in spec.hooks:
                    adapted = context._hook_adapter(item)

                    class Gated(ModeGatedHook):
                        # Keep the existing adapter callback signature.
                        # pylint: disable-next=arguments-renamed
                        async def _run(self, runtime):
                            return await self.adapted.run(runtime)

                    gated = Gated(owner)
                    gated.adapted = adapted
                    for key in (
                        "name",
                        "phase",
                        "priority",
                        "before",
                        "after",
                        "owner_plugin_id",
                    ):
                        setattr(gated, key, getattr(adapted, key))
                    output.append(gated)
                return output

            def prompt_contributors(self):
                owner = self
                output = []
                for item in spec.prompts:

                    class Contributor(SyncPromptContributor):
                        # Keep the existing adapter callback signature.
                        # pylint: disable-next=arguments-renamed
                        def contribute_sync(self, runtime):
                            if (
                                self.spec.workspace_id
                                and runtime.agent_id != self.spec.workspace_id
                            ):
                                return None
                            return (
                                self.spec.text
                                if owner.is_active(runtime)
                                else None
                            )

                    contributor = Contributor()
                    contributor.name, contributor.priority = (
                        item.name,
                        item.priority,
                    )
                    contributor.owner_plugin_id, contributor.spec = (
                        context.plugin_id,
                        item,
                    )
                    output.append(contributor)
                return output

            async def _event(self, callback, runtime):
                if callback is not None:
                    async with context._invocation(
                        workspace_id=runtime.agent_id,
                        session_id=runtime.session_id,
                    ):
                        await context._call(callback, snapshot(runtime))

            # Keep the existing adapter callback signature.
            # pylint: disable-next=arguments-renamed
            async def on_turn_start(self, runtime):
                await self._event(spec.on_turn_start, runtime)

            # Keep the existing adapter callback signature.
            # pylint: disable-next=arguments-renamed
            async def on_conversation_reset(self, runtime):
                await self._event(spec.on_reset, runtime)

        handles = [
            self.register_tool(tool, _mode=spec.name) for tool in spec.tools
        ]
        handles.append(
            self._register_contribution(self._api.register_mode, Adapter),
        )

        async def release():
            nonlocal admitted
            admitted = False
            for handle in reversed(handles):
                await handle.close()

        return Registration(
            release,
            owner=self.resources.owner,
            description=f"mode:{spec.name}",
        )

    def register_skills(self, spec: SkillSpec) -> Registration:
        from pathlib import Path
        from ..utils.io_utils import run_sync_io

        self._guard()
        if getattr(self, "_skills_registered", False):
            raise SDKError("Declare one skill directory per plugin")
        root = Path(self._instance.source_path).resolve()
        directory = (root / spec.directory).resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise SDKError(
                "Skill directory must exist inside the plugin package",
            )
        for entry in directory.rglob("*"):
            if not entry.resolve().is_relative_to(root):
                raise SDKError(
                    "Skill sources must stay inside the plugin package",
                )
        handle = self._register_contribution(
            self._api.register_skill_provider,
            directory,
            enabled_by_default=spec.enabled_by_default,
            channels=list(spec.channels),
        )
        self._skills_registered = True

        async def release():
            if (
                self._loader.lifecycle.get_instance(self.plugin_id)
                is not self._instance
                or getattr(self._instance, "sdk_context", None) is not self
            ):
                return
            await handle.close()
            await run_sync_io(self._api.unregister_skill_provider)
            self._skills_registered = False

        return Registration(
            release,
            owner=self.resources.owner,
            description="skills",
        )

    def register_market(self, spec: MarketSpec) -> Registration:
        from copy import deepcopy
        from .markets import (
            Availability,
            MarketContext,
            SearchPage,
            SkillBundle,
        )
        from ..market.schema import MarketResult as RuntimeResult
        from ..market.registry import market_registry

        context = self

        class Adapter:
            key, label, supports_browse = (
                spec.key,
                spec.label,
                spec.supports_browse,
            )

            def available(self):
                context._guard()
                result = spec.available()
                if not isinstance(result, Availability):
                    raise SDKError(
                        "Market availability must return "
                        "Availability synchronously",
                    )
                return result.available, result.reason

            def matches_url(self, url):
                context._guard()
                result = spec.matches_url(url)
                if not isinstance(result, bool):
                    raise SDKError(
                        "Market matches_url must return bool synchronously",
                    )
                return result

            async def _call(self, callback, *args):
                from ..config.context import get_current_session_id
                from ._workspace import current_workspace_id

                async with context._invocation(
                    workspace_id=current_workspace_id(),
                    session_id=get_current_session_id() or "",
                ) as base:
                    public = MarketContext(
                        **{
                            f.name: getattr(base, f.name) for f in fields(base)
                        },
                        market_id=spec.key,
                    )
                    return await context._call(callback, public, *args)

            async def search(self, query, limit, page):
                result = await self._call(spec.search, query, limit, page)
                if not isinstance(result, SearchPage):
                    raise SDKError("Market search must return SearchPage")
                return (
                    [
                        RuntimeResult(
                            source=spec.key,
                            slug=item.slug,
                            name=item.name,
                            source_url=item.source_url,
                            description=item.description,
                            version=item.version,
                            author=item.author,
                            icon_url=item.icon_url,
                            stats=deepcopy(item.stats),
                        )
                        for item in result.items
                    ],
                    result.has_more,
                    result.total,
                )

            async def fetch_bundle(self, url, requested_version):
                result = await self._call(spec.fetch, url, requested_version)
                if not isinstance(result, SkillBundle):
                    raise SDKError("Market fetch must return SkillBundle")
                return {
                    "name": result.name,
                    "files": deepcopy(result.files),
                    "version": result.version,
                }, result.resolved_url

        self._guard()
        adapter = Adapter()
        self._api.register_market_provider(adapter, priority=spec.priority)

        # The legacy API records owner-wide cleanup for whole-plugin teardown;
        # the public handle revokes this exact provider only.
        async def release():
            if (
                self._loader.lifecycle.get_instance(self.plugin_id)
                is self._instance
                and getattr(self._instance, "sdk_context", None) is self
            ):
                market_registry.unregister(spec.key, expected=adapter)

        return Registration(
            release,
            owner=self.resources.owner,
            description=f"market:{spec.key}",
        )

    def register_provider(self, spec: ProviderSpec) -> Registration:
        from ._providers import register

        return register(self, spec)

    def register_memory(self, spec: MemorySpec) -> Registration:
        from ._memory import register

        return register(self, spec)

    def subscribe_events(self, spec: EventSubscription) -> Registration:
        """Subscribe on activation; overflow reports a gap or disconnect."""
        from ._events import subscribe

        return subscribe(self, spec)

    def register_app(self, app: PawApp) -> Registration:
        from ._apps import register

        return register(self, app)
