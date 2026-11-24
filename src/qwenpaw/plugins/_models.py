# -*- coding: utf-8 -*-
"""
One conversion path for configured-model consumers and the author test host.
"""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from contextlib import contextmanager
from copy import deepcopy
from collections.abc import Mapping
import math
from contextvars import ContextVar

from ._workspace import workspace_id as model_workspace_id

from .errors import SDKError
from .providers import ModelChunk, ModelUsage
from ._messages import to_host, _from_block, _take_previews

model_deadline = ContextVar("sdk_model_deadline", default=None)


def json_mapping(value):
    def convert(item):
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float) and math.isfinite(item):
            return item
        if isinstance(item, (tuple, list)):
            return [convert(part) for part in item]
        if isinstance(item, Mapping) and all(
            isinstance(key, str) for key in item
        ):
            return {key: convert(part) for key, part in item.items()}
        raise SDKError(
            "Fields and model options must contain finite JSON values",
        )

    if not isinstance(value, Mapping):
        raise SDKError("Fields and model options must be mappings")
    return convert(value)


@contextmanager
def model_context(workspace, session_id, workspace_id):
    from ..config.context import current_workspace_dir, current_session_id

    identity_token = model_workspace_id.set(workspace_id)
    workspace_token = current_workspace_dir.set(workspace)
    session_token = current_session_id.set(session_id)
    try:
        yield
    finally:
        current_session_id.reset(session_token)
        current_workspace_dir.reset(workspace_token)
        model_workspace_id.reset(identity_token)


def public_chunk(chunk, content):
    usage = chunk.usage
    metadata, previews, block_metadata = _take_previews(
        chunk.metadata,
        chunk.content,
    )
    return ModelChunk(
        tuple(
            _from_block(block, previews, block_metadata, str(index))
            for index, block in enumerate(content)
        ),
        chunk.is_last,
        (
            ModelUsage(
                usage.input_tokens,
                usage.output_tokens,
                usage.time,
                usage.cache_creation_input_tokens,
                usage.cache_input_tokens,
                deepcopy(usage.metadata or {}),
            )
            if usage
            else None
        ),
        str(chunk.finished_reason),
        chunk.id,
        metadata,
    )


def model_response(chunk):
    from agentscope.model import ChatResponse, ChatUsage
    from dataclasses import asdict
    from .messages import Message

    message = to_host(
        Message("assistant", chunk.content, metadata=chunk.metadata),
    )
    return ChatResponse(
        content=message.content,
        metadata=message.metadata,
        is_last=chunk.is_last,
        usage=ChatUsage(**asdict(chunk.usage)) if chunk.usage else None,
        finished_reason=chunk.finished_reason,
        **({"id": chunk.id} if chunk.id else {}),
    )


class ModelAccumulator:
    """
    Host delta merging, with the existing message codec for SDK block fields.
    """

    def __init__(self):
        from agentscope.model import ChatResponse

        self.response = ChatResponse(content=[], is_last=True)
        self.blocks, self.metadata, self.block_metadata, self.previews = (
            {},
            {},
            {},
            {},
        )

    def append(self, chunk, converted=None):
        from ._messages import _block_key, _merge_refs

        converted = model_response(chunk) if converted is None else converted
        for public, host in zip(chunk.content, converted.content):
            key = _block_key(host)
            _merge_refs(
                self.block_metadata,
                {key: public.metadata},
                "metadata",
            )
            _merge_refs(
                self.previews,
                {
                    key: public.attachment.preview_url
                    if public.attachment
                    else "",
                },
                "preview URLs",
            )
            self.blocks[key] = public
        self.response.append_chat_response(converted)
        self.metadata.update(deepcopy(chunk.metadata))
        self.response.id = converted.id
        self.response.finished_reason = converted.finished_reason

    def finish(self):
        from ._messages import (
            _block_key,
            _with_previews,
            _preview_refs,
            _metadata_refs,
        )

        blocks = self.response.content
        public = [self.blocks[_block_key(block)] for block in blocks]
        self.response.metadata = _with_previews(
            self.metadata,
            _preview_refs(public, blocks),
            blocks,
            _metadata_refs(public, blocks),
        )
        return self.response


async def stream_model(
    model,
    workspace,
    session_id,
    messages,
    tools,
    tool_choice,
    options,
    *,
    workspace_id=None,
):
    from agentscope.tool import ToolChoice
    from agentscope.model import ChatResponse
    from dataclasses import replace
    from ._workspace import configured_workspace_id

    # Resolve once: profile edits cannot revoke transport cleanup halfway
    # through an owned request. SDK callers already carry the actual host ID.
    workspace_id = workspace_id or configured_workspace_id(workspace)
    with model_context(workspace, session_id, workspace_id):
        stream = await model(
            [to_host(message) for message in messages],
            tools=list(tools),
            tool_choice=(
                ToolChoice(
                    mode=tool_choice.mode,
                    tools=(
                        list(tool_choice.tools)
                        if tool_choice.tools is not None
                        else None
                    ),
                )
                if tool_choice
                else None
            ),
            **dict(options or {}),
        )
    if isinstance(stream, ChatResponse):
        if stream.content:
            yield replace(
                public_chunk(stream, stream.content),
                is_last=False,
                usage=None,
            )
        yield public_chunk(stream, ())
        return
    emitted = False
    terminal = False
    try:
        while True:
            with model_context(workspace, session_id, workspace_id):
                try:
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    break
            if terminal:
                raise SDKError("Model yielded after its terminal response")
            terminal = chunk.is_last
            if terminal:
                # Host terminal content is the accumulated summary, not another
                # delta. A terminal-only response still has to deliver its
                # body.
                if not emitted and chunk.content:
                    yield replace(
                        public_chunk(chunk, chunk.content),
                        is_last=False,
                        usage=None,
                    )
                yield public_chunk(chunk, ())
            else:
                emitted = emitted or bool(chunk.content)
                yield public_chunk(chunk, chunk.content)
        if not terminal:
            raise SDKError("Model stream ended without a terminal response")
    finally:
        with model_context(workspace, session_id, workspace_id):
            await stream.aclose()


class ModelLease:
    """
    Own only models constructed for this request, never a provider manager.
    """

    def __init__(self):
        self.model = None
        self.streams = []
        self.clients = []
        self.wrappers = []
        self._seen = {}

    def before_create(self, provider):
        import inspect

        method = inspect.unwrap(provider.get_chat_model_instance)
        supported = {
            ("openai_provider", "OpenAIProvider"),
            ("openai_provider", "OpenCodeProvider"),
            ("openai_response_provider", "OpenAIResponseProvider"),
            ("anthropic_provider", "AnthropicProvider"),
            ("gemini_provider", "GeminiProvider"),
            ("dashscope_provider", "DashScopeProvider"),
            ("ollama_provider", "OllamaProvider"),
            ("openrouter_provider", "OpenRouterProvider"),
            ("hub_managed", "ManagedProvider"),
        }
        known = any(
            method.__module__ == f"qwenpaw.providers.{module}"
            and method.__qualname__ == f"{owner}.get_chat_model_instance"
            for module, owner in supported
        )
        sdk = (
            method.__module__ == "qwenpaw.plugins._providers"
            and method.__qualname__
            == "register.<locals>.Adapter.get_chat_model_instance"
        )
        if not known and not sdk:
            raise SDKError(
                "This configured provider factory has no supported SDK "
                "request ownership adapter",
            )

    def capture(self, root=None):
        from ..providers.retry_chat_model import RetryChatModel
        from ..providers.fallback_chat_model import FallbackChatModel
        from ..token_usage.model_wrapper import TokenRecordingModelWrapper
        import inspect

        def visit(model):
            if id(model) in self._seen:
                return
            self._seen[id(model)] = model
            if isinstance(model, FallbackChatModel):
                for item in model._models:
                    visit(item)
                return
            if isinstance(model, RetryChatModel):
                self.wrappers.append(model)
                visit(model._inner)
                return
            if isinstance(model, TokenRecordingModelWrapper):
                visit(model._model)
                return
            if type(model).__module__ == "qwenpaw.plugins._providers":
                # SDK providers already own their clients/scopes and producers.
                return
            supported = (
                "agentscope.model._openai_chat",
                "agentscope.model._openai_response",
                "agentscope.model._anthropic",
                "agentscope.model._gemini",
                "agentscope.model._dashscope",
            )
            if not any(
                cls.__module__.startswith(supported)
                for cls in type(model).__mro__
            ):
                raise SDKError(
                    "This configured model type has no supported SDK request "
                    "ownership adapter",
                )
            client = model.client
            if not any(client is item for item in self.clients):
                self.clients.append(client)
            original = model._call_api

            async def captured(*args, **kwargs):
                result = original(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                if hasattr(result, "aclose"):
                    self.streams.append(result)
                return result

            # This is a fresh, request-local factory instance. The host class,
            # provider and other agents' models retain their original methods.
            model._call_api = captured

        visit(self.model if root is None else root)

    async def close(self):
        import asyncio
        import inspect
        from ..utils.io_utils import run_sync_io

        while pending := {
            task
            for model in self.wrappers
            for task in model._pending_provider_cleanup_tasks
            if not task.done()
        }:
            await asyncio.wait(pending)
        for stream in tuple(self.streams):
            await stream.aclose()
            self.streams.remove(stream)
        for client in tuple(self.clients):
            aio = getattr(client, "aio", None)
            if aio is not None and callable(getattr(aio, "aclose", None)):
                await aio.aclose()
            closer = getattr(client, "aclose", None) or getattr(
                client,
                "close",
                None,
            )
            if closer is None:
                raise SDKError("The configured model client cannot be closed")
            if inspect.iscoroutinefunction(closer):
                await closer()
            else:
                result = await run_sync_io(closer)
                if inspect.isawaitable(result):
                    await result
            self.clients.remove(client)
