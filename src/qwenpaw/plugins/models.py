# -*- coding: utf-8 -*-
"""Single model requests using the calling workspace's configured providers."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from copy import deepcopy
from typing import Any

from .events import JSONValue
from .messages import Message
from .providers import ModelChunk, ModelToolChoice
from .errors import SDKError, StaleContextError

# These are generation controls, never alternate credentials, endpoints or
# input.
_OPTIONS = frozenset(
    {
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "stop",
        "seed",
        "frequency_penalty",
        "presence_penalty",
        "parallel_tool_calls",
        "reasoning_effort",
        "thinking_budget",
        "enable_thinking",
    },
)


class ModelService:
    """
    Use context.models; each request remains owned by that callback scope.
    """

    def __init__(self, context):
        self._context = context

    def _guard(self):
        context = self._context
        if context._plugin is None:
            raise SDKError("Model services are created by the host")
        context._plugin._guard()
        if (
            context.resources.closed
            or context.resources._closing
            or context.cancelled
        ):
            raise StaleContextError("The model caller's scope has ended")
        if not context.workspace_id:
            raise SDKError("Model requests require a workspace-bound context")

    # Keep the ownership state machine in one scope.
    # pylint: disable-next=too-many-statements
    async def stream(
        self,
        messages: Sequence[Message],
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: Sequence[dict[str, Any]] = (),
        tool_choice: ModelToolChoice | None = None,
        options: Mapping[str, JSONValue] | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[ModelChunk, None]:
        from ._models import json_mapping, model_context, stream_model
        from ..config.utils import load_config
        from pathlib import Path
        from ..agents.model_factory import (
            create_model_and_formatter,
            _model_creation_observer,
        )
        from ..providers.provider_manager import (
            ProviderManager,
            ModelSlotConfig,
        )
        from ..utils.io_utils import run_sync_io
        import math

        self._guard()
        if (
            bool(provider_id) != bool(model_id)
            or provider_id == ""
            or model_id == ""
        ):
            raise SDKError(
                "provider_id and model_id must be supplied together",
            )
        values = json_mapping({} if options is None else options)
        if unknown := values.keys() - _OPTIONS:
            raise SDKError(
                f"Unsupported model options: {', '.join(sorted(unknown))}",
            )
        if timeout is not None and (
            not math.isfinite(timeout) or timeout <= 0
        ):
            raise SDKError("Model timeout must be finite and positive")
        context = self._context
        plugin = context._plugin
        deadline = context.deadline
        if timeout is not None:
            requested = asyncio.get_running_loop().time() + timeout
            deadline = (
                requested if deadline is None else min(deadline, requested)
            )
        messages = deepcopy(tuple(messages))
        tools = tuple(json_mapping(tool) for tool in tools)
        names = set()
        for tool in tools:
            function = tool.get("function")
            if (
                tool.get("type") != "function"
                or not isinstance(function, dict)
                or not isinstance(function.get("name"), str)
                or not function["name"]
                or not isinstance(function.get("parameters", {}), dict)
            ):
                raise SDKError(
                    "Model tools require function declarations with a name "
                    "and schema",
                )
            if function["name"] in names:
                raise SDKError("Model tool names must be unique")
            names.add(function["name"])
        if tool_choice is not None:
            selected = (
                names if tool_choice.tools is None else set(tool_choice.tools)
            )
            if not selected <= names or tool_choice.mode not in {
                "auto",
                "none",
                "required",
                *selected,
            }:
                raise SDKError(
                    "Model tool choice refers to an undeclared tool",
                )
            if tool_choice.mode == "required" and not selected:
                raise SDKError(
                    "Required tool choice needs at least one declared tool",
                )

        def build():
            reference = load_config().agents.profiles.get(context.workspace_id)
            if reference is None or not reference.enabled:
                raise SDKError(
                    "The calling workspace is not configured and enabled",
                )
            workspace = Path(reference.workspace_dir).expanduser()
            override = None
            if provider_id is not None:
                provider = ProviderManager.get_instance().get_provider(
                    provider_id,
                )
                if (
                    provider is None
                    or not provider.enabled
                    or provider.get_model_info(model_id) is None
                ):
                    raise SDKError(
                        "The selected provider/model is not configured and "
                        "enabled",
                    )
                override = ModelSlotConfig(
                    provider_id=provider_id,
                    model=model_id,
                )
            token = _model_creation_observer.set(lease)
            try:
                with model_context(
                    workspace,
                    context.session_id,
                    context.workspace_id,
                ):
                    lease.model = create_model_and_formatter(
                        agent_id=context.workspace_id,
                        model_slot_override=override,
                    )[0]
            finally:
                _model_creation_observer.reset(token)
            lease.capture()
            return lease.model, workspace

        async def produce():
            from ._models import ModelLease, model_deadline, model_workspace_id
            from ..agents.context.overflow_recovery import _stream_observer
            from .sdk import _RunStreams, _stream_tasks

            nonlocal lease
            self._guard()
            async with plugin._invocation(
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                deadline=deadline,
            ) as base:
                lease = ModelLease()
                base.resources.defer(lease.close, "configured model transport")
                owned = _RunStreams()
                owner_token = _stream_tasks.set(owned)
                observer_token = _stream_observer.set(owned.retain)
                deadline_token = model_deadline.set(deadline)
                workspace_token = model_workspace_id.set(context.workspace_id)
                try:
                    model, workspace = await run_sync_io(build)
                    source = stream_model(
                        model,
                        workspace,
                        context.session_id,
                        messages,
                        tools,
                        tool_choice,
                        values,
                        workspace_id=context.workspace_id,
                    )
                    try:
                        async for chunk in source:
                            yield chunk
                    finally:
                        await source.aclose()
                except Exception as exc:
                    if isinstance(exc, SDKError):
                        raise
                    raise SDKError(
                        f"Configured model request failed: "
                        f"{type(exc).__name__}: {exc}",
                    ) from exc
                finally:
                    owned.closing = True
                    _stream_observer.reset(observer_token)
                    _stream_tasks.reset(owner_token)
                    model_deadline.reset(deadline_token)
                    model_workspace_id.reset(workspace_token)
                    while pending := {
                        task for task in owned.tasks if not task.done()
                    }:
                        for task in pending:
                            task.cancel()
                        try:
                            await asyncio.wait(pending)
                        except asyncio.CancelledError:
                            pass
                    while owned.streams or owned.scopes:
                        for close in owned.closers():
                            try:
                                await close()
                            except (Exception, asyncio.CancelledError):
                                pass
                        if owned.streams or owned.scopes:
                            await plugin._instance.activity.retry_cleanup()

        lease = None
        stream = plugin._managed_stream(
            produce,
            "configured model request",
            deadline=deadline,
            resources=context.resources,
        )
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: Sequence[dict[str, Any]] = (),
        tool_choice: ModelToolChoice | None = None,
        options: Mapping[str, JSONValue] | None = None,
        timeout: float | None = None,
    ) -> ModelChunk:
        from ._models import ModelAccumulator, public_chunk

        accumulated = ModelAccumulator()
        stream = self.stream(
            messages,
            provider_id=provider_id,
            model_id=model_id,
            tools=tools,
            tool_choice=tool_choice,
            options=options,
            timeout=timeout,
        )
        try:
            async for chunk in stream:
                accumulated.append(chunk)
        finally:
            await stream.aclose()
        result = accumulated.finish()
        return public_chunk(result, result.content)
