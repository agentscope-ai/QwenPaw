# -*- coding: utf-8 -*-
"""Provider contracts adapted to host inference, state and lifecycle."""

# Host adapters own private lifecycle state.
# pylint: disable=protected-access

import asyncio
import inspect
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import asdict, fields, replace
from typing import ClassVar

from .errors import SDKError, StaleContextError
from .providers import (
    ConnectionResult,
    ModelChunk,
    ModelRequest,
    ModelToolChoice,
    ProviderContext,
    ProviderHandle,
)
from .storage import PluginConfig

_turn_usage = ContextVar("provider_turn_usage", default=None)


def model_values(model):
    return {
        key: value for key, value in asdict(model).items() if value is not None
    }


class ProviderTurn:
    """Retain provider uses and suspended streams until the Agent turn ends."""

    def __init__(self):
        self.task = asyncio.current_task()
        self.leases = []
        self.producers = set()
        self.lock = asyncio.Lock()
        self.closed = False
        self.token = _turn_usage.set(self)

    async def close(self):
        if self.closed and not self.producers and not self.leases:
            return
        self.closed = True
        try:
            if self.producers or self.leases:
                from ..utils.io_utils import run_async_to_completion

                await run_async_to_completion(self._close_resources())
        finally:
            if self.token is not None:
                _turn_usage.reset(self.token)
                self.token = None

    async def _close_resources(self):
        from .custody import stop_task

        for producer in tuple(self.producers):
            await stop_task(producer, "provider-inference")
        while self.leases:
            await self.leases[-1].__aexit__(None, None, None)
            self.leases.pop()


class ProviderBinding:
    def __init__(self, context, spec):
        self.context = context
        self.spec = spec
        self.closed = False

    def guard(self):
        self.context._guard()
        if self.closed:
            raise StaleContextError(
                f"Provider {self.spec.id!r} has been released",
            )

    def provider(self):
        from ..providers.provider_manager import ProviderManager

        self.guard()
        provider = ProviderManager.get_instance().get_provider(self.spec.id)
        if provider is None:
            raise StaleContextError(
                f"Provider {self.spec.id!r} is unavailable",
            )
        return provider

    async def select(self, model_id):
        from ..exceptions import AppBaseException
        from ..providers.provider_manager import ProviderManager

        with self.context._admission():
            self.provider()
            manager = ProviderManager.get_instance()
            try:
                await manager.activate_model(self.spec.id, model_id)
            except AppBaseException as exc:
                raise SDKError(str(exc)) from exc

    async def clear_selection(self):
        from ..providers.provider_manager import ProviderManager

        with self.context._admission():
            self.provider()
            manager = ProviderManager.get_instance()
            return await manager.clear_active_model_async(self.spec.id)

    async def update(
        self,
        *,
        base_url=None,
        models=None,
        generate_kwargs=None,
    ):
        from ..providers.provider_manager import ProviderManager
        from ..providers.model_info import ModelInfo

        with self.context._admission():
            provider = self.provider()
            values = {}
            if base_url is not None:
                values["base_url"] = base_url
            if models is not None:
                existing = {model.id: model for model in provider.extra_models}
                published = []
                for model in models:
                    previous = existing.get(model.id)
                    item = previous.model_dump() if previous else {}
                    item.update(model_values(model))
                    published.append(ModelInfo.model_validate(item))
                values["extra_models"] = published
            if generate_kwargs is not None:
                values["generate_kwargs"] = deepcopy(generate_kwargs)
            values = {
                key: value
                for key, value in values.items()
                if getattr(provider, key) != value
            }
            if values:
                await ProviderManager.get_instance().update_provider_async(
                    self.spec.id,
                    values,
                )

    async def restore_selected(self):
        """Prepare a published model selected by an enabled Agent."""
        from ..providers.provider_manager import ProviderManager
        from ..utils.io_utils import run_sync_io

        manager = ProviderManager.get_instance()
        choices = await run_sync_io(configured_models, manager)
        selected = {
            slot.model
            for slot in choices
            if manager._normalize_provider_id(slot.provider_id) == self.spec.id
        }
        provider = self.provider()
        if not provider.enabled:
            return
        model = next(
            (model for model in provider.all_models() if model.id in selected),
            None,
        )
        if model is not None:
            async with self.connect(model.id):
                pass

    @asynccontextmanager
    async def invocation(self, provider, deadline=None, *, owner=None):
        from ..config.context import get_current_session_id
        from ._workspace import current_workspace_id

        self.guard()
        async with self.context._invocation(
            workspace_id=current_workspace_id(),
            session_id=get_current_session_id() or "",
            owner=owner,
            deadline=deadline,
        ) as base:
            values = dict(self.context._api.config)
            values["api_key"] = provider.api_key
            secrets = [
                "api_key",
                *(self.context._api.manifest.get("sdk") or {}).get(
                    "secrets",
                    [],
                ),
            ]
            public = ProviderContext(
                **{
                    field.name: getattr(base, field.name)
                    for field in fields(base)
                },
                provider_id=self.spec.id,
                base_url=provider.base_url,
                headers=deepcopy(provider.custom_headers),
            )
            yield replace(
                public,
                config=PluginConfig(values, {"secrets": secrets}),
            )

    @asynccontextmanager
    async def _lease(self, model_id, owner):
        async with self.invocation(self.provider(), owner=owner) as public:
            if self.spec.connect is None:
                yield public.base_url
                return
            async with self.spec.connect(public, model_id) as endpoint:
                if not isinstance(endpoint, str) or not endpoint:
                    raise SDKError(
                        "Provider connect must yield a nonempty base URL",
                    )
                yield endpoint

    @asynccontextmanager
    async def connect(self, model_id):
        self.guard()
        turn = _turn_usage.get()
        if turn is None:
            async with self._lease(
                model_id,
                asyncio.current_task(),
            ) as endpoint:
                yield endpoint
            return
        async with turn.lock:
            if turn.closed:
                raise StaleContextError("The owning Agent turn has ended")
            lease = self._lease(model_id, turn.task)
            endpoint = await lease.__aenter__()
            turn.leases.append(lease)
        yield endpoint

    async def call(self, model, *args, **kwargs):
        """Keep the native formatter and response stream, including aclose."""

        async def invoke(endpoint):
            # Request-local settings keep concurrent calls independent.
            request_model = copy(model)
            request_model.client = model.client.with_options(base_url=endpoint)
            return await request_model._call_native(*args, **kwargs)

        if not model.stream:
            async with self.connect(model.model) as endpoint:
                return await invoke(endpoint)

        turn = _turn_usage.get()

        async def produce():
            if turn is not None and turn.closed:
                raise StaleContextError("The owning Agent turn has ended")
            token = _turn_usage.set(turn)
            producer = asyncio.current_task()
            if turn is not None:
                turn.producers.add(producer)
            try:
                async with self.connect(model.model) as endpoint:
                    response = await invoke(endpoint)
                    # Native cancellation can return one interrupted response.
                    if not inspect.isasyncgen(response):
                        yield response
                        return
                    try:
                        async for chunk in response:
                            yield chunk
                    finally:
                        await response.aclose()
            finally:
                if turn is not None:
                    turn.producers.discard(producer)
                _turn_usage.reset(token)

        return self.context._managed_stream(
            produce,
            f"provider:{self.spec.id}",
        )

    def handle(self, registration):
        async def release():
            self.closed = True
            await registration.close()

        handle = ProviderHandle(
            release,
            owner=self.context.resources.owner,
            description=f"provider:{self.spec.id}",
        )
        handle._provider = self
        return handle


def register_native(context, spec):
    from ..providers.openai_provider import OpenAIProvider
    from ..providers.openai_chat_model_compat import OpenAIChatModelCompat
    from ..providers.model_info import ModelInfo

    binding = ProviderBinding(context, spec)

    class Model(OpenAIChatModelCompat):
        async def __call__(self, *args, **kwargs):
            return await binding.call(self, *args, **kwargs)

        async def _call_native(self, *args, **kwargs):
            return await super().__call__(*args, **kwargs)

    class Adapter(OpenAIProvider):
        _sdk_binding: ClassVar[ProviderBinding] = binding

        @classmethod
        def get_default_models(cls):
            return [ModelInfo(**model_values(item)) for item in spec.models]

        def get_chat_model_instance(self, model_id):
            binding.guard()
            return super().get_chat_model_instance(model_id)

        @staticmethod
        def _create_chat_model(**kwargs):
            return Model(**kwargs)

        async def check_model_connection(self, model_id, timeout=5):
            async with binding.connect(model_id) as endpoint:
                provider = self.configuration_snapshot()
                provider.base_url = endpoint
                return await OpenAIProvider.check_model_connection(
                    provider,
                    model_id,
                    timeout,
                )

        async def probe_model_multimodal(
            self,
            model_id,
            timeout=60,
            image_only=False,
        ):
            async with binding.connect(model_id) as endpoint:
                provider = self.configuration_snapshot()
                provider.base_url = endpoint
                return await OpenAIProvider.probe_model_multimodal(
                    provider,
                    model_id,
                    timeout,
                    image_only=image_only,
                )

        async def fetch_models(self, timeout=5):
            if spec.discover is None:
                return await super().fetch_models(timeout)
            async with (
                asyncio.timeout(timeout),
                binding.invocation(self) as public,
            ):
                models = await context._call(spec.discover, public, timeout)
                return [ModelInfo(**model_values(item)) for item in models]

        async def check_connection(self, timeout=5):
            if spec.check_connection is None:
                return await super().check_connection(timeout)
            async with (
                asyncio.timeout(timeout),
                binding.invocation(self) as public,
            ):
                result = await context._call(
                    spec.check_connection,
                    public,
                    timeout,
                )
                if not isinstance(result, ConnectionResult):
                    raise SDKError(
                        "Provider check_connection must return "
                        "ConnectionResult",
                    )
                return result.success, result.message

    context._guard()
    registration = context._register_contribution(
        context._api.register_provider,
        spec.id,
        Adapter,
        label=spec.label,
        base_url=spec.base_url,
        require_api_key=spec.require_api_key,
        is_local=spec.is_local,
        support_model_discovery=spec.discover is not None,
    )
    return binding.handle(registration)


# Keep the ownership state machine in one scope.
# pylint: disable-next=too-many-statements
def register(context, spec):
    if spec.protocol is not None:
        if spec.protocol != "openai-chat" or spec.generate is not None:
            raise SDKError("Choose a supported protocol or generate, not both")
        return register_native(context, spec)
    if spec.generate is None:
        raise SDKError("Provider requires generate or a supported protocol")
    if spec.connect is not None:
        raise SDKError("Provider connect requires a native protocol")
    from agentscope.credential import CredentialBase
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.model import ChatModelBase
    from ..providers.provider import Provider
    from ..providers.model_info import ModelInfo
    from ._messages import from_host
    from ._models import ModelAccumulator, model_response

    binding = ProviderBinding(context, spec)
    guard = binding.guard
    invocation = binding.invocation

    def response(chunk):
        if not isinstance(chunk, ModelChunk):
            raise SDKError(
                "Provider generate must return ModelChunk or stream "
                "ModelChunk values",
            )
        if any(
            block.type in {"hint", "tool_result"} for block in chunk.content
        ):
            raise SDKError(
                "Model output supports text, thinking, tool_call and "
                "attachments",
            )
        return model_response(chunk)

    class Model(ChatModelBase):
        def __init__(self, provider, model_id):
            super().__init__(
                CredentialBase(),
                model_id,
                self.Parameters(),
                max_retries=0,
                context_size=provider.get_context_size(model_id),
            )
            self.provider = provider
            self.formatter = OpenAIChatFormatter(
                input_types=[
                    "text/plain",
                    "image/*",
                    "audio/*",
                    "video/*",
                    "application/*",
                ],
            )

        # Keep the ownership state machine in one scope.
        # pylint: disable-next=too-many-branches
        async def _generate(self, request):
            async with invocation(self.provider) as public:
                if inspect.isasyncgenfunction(spec.generate):
                    result = spec.generate(public, request)
                else:
                    result = await context._call(
                        spec.generate,
                        public,
                        request,
                    )
                if isinstance(result, ModelChunk):
                    if not result.is_last:
                        raise SDKError(
                            "A non-streamed ModelChunk must be terminal",
                        )
                    converted = response(result)
                    if converted.content:
                        yield replace(converted, is_last=False, usage=None)
                    yield converted
                    return
                if not hasattr(result, "__aiter__"):
                    raise SDKError(
                        "Provider generate must return ModelChunk or an "
                        "async stream",
                    )
                terminal = False
                terminal_response = None
                complete = ModelAccumulator()
                try:
                    async for chunk in result:
                        if terminal:
                            raise SDKError(
                                "Model stream yielded after its terminal "
                                "chunk",
                            )
                        converted = response(chunk)
                        complete.append(chunk, converted)
                        terminal = chunk.is_last
                        if terminal:
                            terminal_response = converted
                        else:
                            yield converted
                    if not terminal:
                        raise SDKError(
                            "Model stream ended without a terminal chunk",
                        )
                    if terminal_response.content:
                        yield replace(
                            terminal_response,
                            is_last=False,
                            usage=None,
                        )
                    yield complete.finish()
                finally:
                    close = getattr(result, "aclose", None)
                    if close is not None:
                        await close()

        async def _call_api(
            self,
            model_name,
            messages,
            tools=None,
            tool_choice=None,
            **kwargs,
        ):
            guard()
            choice = None
            if tool_choice is not None:
                choice = ModelToolChoice(
                    tool_choice
                    if isinstance(tool_choice, str)
                    else tool_choice.mode,
                    (
                        tuple(tool_choice.tools)
                        if getattr(tool_choice, "tools", None) is not None
                        else None
                    ),
                )
            request = ModelRequest(
                model_name,
                tuple(from_host(message) for message in messages),
                tuple(deepcopy(tools or [])),
                choice,
                {
                    **deepcopy(self.provider.generate_kwargs),
                    **deepcopy(kwargs),
                },
            )
            return context._managed_stream(
                lambda: self._generate(request),
                f"provider:{spec.id}:{model_name}",
            )

        async def __call__(
            self,
            messages,
            tools=None,
            tool_choice=None,
            **kwargs,
        ):
            # Preserve aclose through the SDK stream; host
            # token/retry/rate-limit
            # wrappers still surround this model in create_model_and_formatter.
            return await self._call_api(
                self.model,
                messages,
                tools,
                tool_choice,
                **kwargs,
            )

    class Adapter(Provider):
        _sdk_binding: ClassVar[ProviderBinding] = binding

        @classmethod
        def get_default_models(cls):
            return [ModelInfo(**model_values(item)) for item in spec.models]

        async def check_connection(self, timeout=5):
            async with (
                asyncio.timeout(timeout),
                invocation(
                    self,
                    asyncio.get_running_loop().time() + timeout,
                ) as public,
            ):
                if spec.check_connection is None:
                    return (
                        False,
                        "This provider does not declare a connection check",
                    )
                result = await context._call(
                    spec.check_connection,
                    public,
                    timeout,
                )
                if not isinstance(result, ConnectionResult):
                    raise SDKError(
                        "Provider check_connection must return "
                        "ConnectionResult",
                    )
                return result.success, result.message

        async def fetch_models(self, timeout=5):
            async with (
                asyncio.timeout(timeout),
                invocation(
                    self,
                    asyncio.get_running_loop().time() + timeout,
                ) as public,
            ):
                result = (
                    spec.models
                    if spec.discover is None
                    else await context._call(spec.discover, public, timeout)
                )
                return [ModelInfo(**model_values(item)) for item in result]

        async def check_model_connection(self, model_id, timeout=5):
            model = self.get_chat_model_instance(model_id)
            from agentscope.message import Msg, TextBlock

            stream = await model(
                [
                    Msg(
                        name="user",
                        role="user",
                        content=[TextBlock(text="Reply OK")],
                    ),
                ],
            )
            try:
                async with asyncio.timeout(timeout):
                    async for chunk in stream:
                        if chunk.is_last:
                            return True, "Model returned a terminal response"
            finally:
                await stream.aclose()
            return False, "Model returned no terminal response"

        def get_chat_model_instance(self, model_id):
            guard()
            return Model(self, model_id)

    context._guard()
    handle = context._register_contribution(
        context._api.register_provider,
        spec.id,
        Adapter,
        label=spec.label,
        base_url=spec.base_url,
        require_api_key=spec.require_api_key,
        is_local=spec.is_local,
        support_model_discovery=spec.discover is not None,
    )
    return binding.handle(handle)


def configured_models(provider_manager):
    """Read effective chat selections without constructing model clients."""
    from ..config.utils import load_config
    from ..config.config import load_agent_config

    config = load_config()
    choices = []
    for agent_id, profile in config.agents.profiles.items():
        if not profile.enabled:
            continue
        slot = load_agent_config(agent_id).active_model
        if slot is None or not slot.provider_id or not slot.model:
            slot = provider_manager.active_model
        if slot is not None:
            choices.append(slot)
    if not config.agents.profiles and provider_manager.active_model:
        choices.append(provider_manager.active_model)
    return choices


def restore_selected_providers(registry):
    """Schedule selected endpoint preparation after plugin activation."""
    for registration in registry.get_all_providers().values():
        binding = getattr(registration.provider_class, "_sdk_binding", None)
        if binding is None or binding.spec.connect is None:
            continue

        async def restore(current=binding):
            try:
                await current.restore_selected()
            except Exception:
                current.context.logger.exception(
                    "Could not prepare selected model",
                    fields={"provider_id": current.spec.id},
                )

        binding.context.resources.task(restore(), "provider-restore")
