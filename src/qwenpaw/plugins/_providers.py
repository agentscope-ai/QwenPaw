# -*- coding: utf-8 -*-
"""Provider contracts adapted to host inference, state and lifecycle."""

# Host adapters own private lifecycle state.
# pylint: disable=protected-access

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from copy import copy, deepcopy
from dataclasses import asdict, fields, replace
from typing import ClassVar

from ..runtime.turn_context import current_provider_turn
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

logger = logging.getLogger(__name__)


def model_values(model):
    return {
        key: value for key, value in asdict(model).items() if value is not None
    }


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

    def published_model_ids(self) -> tuple[str, ...]:
        from ..providers.provider_manager import ProviderManager

        self.guard()
        manager = ProviderManager.get_instance()
        key = manager._normalize_provider_id(self.spec.id)
        registered = manager.plugin_providers.get(key)
        if registered is None:
            raise StaleContextError(
                f"Provider {self.spec.id!r} is unavailable",
            )
        return tuple(model.id for model in registered["info"].extra_models)

    async def select(self, model_id, *, model_type="chat"):
        from ..exceptions import AppBaseException
        from ..providers.provider_manager import ProviderManager

        with self.context._admission():
            self.provider()
            manager = ProviderManager.get_instance()
            try:
                await manager.activate_model(
                    self.spec.id,
                    model_id,
                    model_type=model_type,
                )
            except AppBaseException as exc:
                raise SDKError(str(exc)) from exc

    async def clear_selection(self, *, model_type="chat"):
        from ..providers.provider_manager import ProviderManager

        with self.context._admission():
            self.provider()
            manager = ProviderManager.get_instance()
            return await manager.clear_active_model_async(
                self.spec.id,
                model_type=model_type,
            )

    async def update(
        self,
        *,
        base_url=None,
        models=None,
        generate_kwargs=None,
    ):
        from ..providers.provider_manager import ProviderManager
        from ..providers.model_info import ModelInfo

        def changes(provider):
            values = {}
            if base_url is not None:
                values["base_url"] = base_url
            if models is not None:
                published = []
                for model in models:
                    previous = provider.get_model_info(model.id)
                    item = previous.model_dump() if previous else {}
                    metadata = model_values(model)
                    if previous is not None:
                        for field in previous.config_overrides:
                            metadata.pop(field, None)
                        if previous.max_input_length_configured:
                            metadata.pop("max_input_length", None)
                    item.update(metadata)
                    published.append(ModelInfo.model_validate(item))
                values["extra_models"] = published
            if generate_kwargs is not None:
                values["generate_kwargs"] = deepcopy(generate_kwargs)
            return {
                key: value
                for key, value in values.items()
                if getattr(provider, key) != value
            }

        with self.context._admission():
            self.guard()
            if not await ProviderManager.get_instance().update_provider_async(
                self.spec.id,
                changes,
            ):
                raise StaleContextError(f"Provider {self.spec.id!r} changed")

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
        from ._identity import request_identity
        from ._workspace import current_workspace_id

        self.guard()
        identity = request_identity.get()
        async with self.context._invocation(
            workspace_id=(
                identity.workspace_id if identity else current_workspace_id()
            ),
            session_id=(
                identity.session_id
                if identity
                else get_current_session_id() or ""
            ),
            owner=owner,
            deadline=deadline,
            identity=identity,
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
    async def _lease(self, model_id, owner, purpose):
        async with self.invocation(self.provider(), owner=owner) as public:
            connect = self.spec.connect
            if connect is None:
                yield public.base_url
                return
            public = replace(public, connection_purpose=purpose)
            async with connect(public, model_id) as endpoint:
                if not isinstance(endpoint, str) or not endpoint:
                    raise SDKError(
                        "Provider connect must yield a nonempty base URL",
                    )
                yield endpoint

    @asynccontextmanager
    async def connect(self, model_id, purpose="inference"):
        self.guard()
        turn = current_provider_turn.get()
        if turn is not None:
            turn.guard()
        owner = turn.task if turn is not None else asyncio.current_task()
        async with self._lease(model_id, owner, purpose) as endpoint:
            if turn is not None:
                turn.retain(self.context, self.context._admission(owner=owner))
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

        turn = current_provider_turn.get()

        async def produce():
            if turn is not None:
                turn.guard()
            token = current_provider_turn.set(turn)
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
                current_provider_turn.reset(token)

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
    from ..providers.provider import ModelConnectionResult
    from ..providers.local_decision_model import (
        LocalDecisionModel,
        LocalDecisionProviderMixin,
    )

    binding = ProviderBinding(context, spec)

    class Model(OpenAIChatModelCompat):
        async def __call__(self, *args, **kwargs):
            return await binding.call(self, *args, **kwargs)

        async def _call_native(self, *args, **kwargs):
            return await super().__call__(*args, **kwargs)

    class DecisionModel(LocalDecisionModel):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._settings = kwargs

        async def __call__(self, *args, **kwargs):
            from ..utils.io_utils import run_async_to_completion

            async with binding.connect(self.model) as endpoint:
                base_url = endpoint.rstrip("/").removesuffix("/v1")
                credential = self._settings["credential"]
                if base_url == credential.base_url:
                    return await super().__call__(*args, **kwargs)
                # A restarted runtime can have a different port. Keep each
                # call's client independent of other in-flight requests.
                model = LocalDecisionModel(
                    **{
                        **self._settings,
                        "credential": credential.model_copy(
                            update={"base_url": base_url},
                        ),
                    },
                )
                try:
                    return await model(*args, **kwargs)
                finally:
                    await run_async_to_completion(model.client.aclose())

    class Adapter(LocalDecisionProviderMixin, OpenAIProvider):
        _sdk_binding: ClassVar[ProviderBinding] = binding
        connection_check_requires_activation: ClassVar[bool] = (
            spec.connect is not None or spec.check_connection is not None
        )

        @classmethod
        def get_default_models(cls):
            return [ModelInfo(**model_values(item)) for item in spec.models]

        def get_chat_model_instance(self, model_id):
            binding.guard()
            return super().get_chat_model_instance(model_id)

        @staticmethod
        def _create_chat_model(**kwargs):
            return Model(**kwargs)

        @staticmethod
        def _create_decision_model(**kwargs):
            binding.guard()
            return DecisionModel(**kwargs)

        async def check_model_connection(self, model_id, timeout=5):
            try:
                if not self.connection_check_requires_activation:
                    binding.guard()
                    async with asyncio.timeout(timeout):
                        with binding.context._admission():
                            return await OpenAIProvider.check_model_connection(
                                self.configuration_snapshot(),
                                model_id,
                                timeout,
                            )
                async with (
                    asyncio.timeout(timeout) as budget,
                    binding.connect(model_id, purpose="check") as endpoint,
                ):
                    provider = self.configuration_snapshot()
                    provider.base_url = endpoint
                    deadline = budget.when()
                    remaining = None
                    if deadline is not None:
                        remaining = (
                            deadline - asyncio.get_running_loop().time()
                        )
                        if remaining <= 0:
                            raise TimeoutError
                    return await OpenAIProvider.check_model_connection(
                        provider,
                        model_id,
                        remaining,
                    )
            except TimeoutError:
                return ModelConnectionResult(
                    success=False,
                    message="Model connection check timed out",
                    verification="unverified",
                )
            except Exception as exc:
                return ModelConnectionResult(
                    success=False,
                    message=self.connection_error_message(exc),
                    verification="unverified",
                )

        async def probe_model_multimodal(
            self,
            model_id,
            timeout=60,
            image_only=False,
        ):
            async with self._multimodal_probe(model_id) as probe:
                return await probe(
                    self,
                    model_id,
                    timeout,
                    image_only=image_only,
                )

        @asynccontextmanager
        async def _multimodal_probe(self, model_id):
            self.validate_chat_model(model_id)
            async with binding.connect(model_id, purpose="probe") as endpoint:

                async def probe(
                    provider,
                    model_id,
                    timeout=60,
                    image_only=False,
                ):
                    prepared = provider.configuration_snapshot()
                    prepared.base_url = endpoint
                    return await OpenAIProvider.probe_model_multimodal(
                        prepared,
                        model_id,
                        timeout,
                        image_only=image_only,
                    )

                yield probe

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
        connection_check_requires_activation: ClassVar[bool] = True

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
    """Read effective typed selections without constructing model clients."""
    from ..config.utils import load_config
    from ..config.config import load_agent_config
    from ..exceptions import ConfigurationException

    config = load_config()
    choices = []
    for agent_id, profile in config.agents.profiles.items():
        if not profile.enabled:
            continue
        try:
            agent = load_agent_config(agent_id)
        except ConfigurationException:
            logger.warning(
                "Skipping model restoration for unreadable Agent config %s",
                agent_id,
                exc_info=True,
            )
            continue
        for model_type, slot in (
            ("chat", agent.active_model),
            ("decision", agent.decision_model),
        ):
            if slot is None or not slot.provider_id or not slot.model:
                slot = provider_manager.default_models[model_type]
            if slot is not None:
                choices.append(slot)
    if not config.agents.profiles:
        choices.extend(
            slot for slot in provider_manager.default_models.values() if slot
        )
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
