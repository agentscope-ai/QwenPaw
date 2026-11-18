# -*- coding: utf-8 -*-
"""SDK-only model adapter through the production provider/model factories."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

import inspect
import asyncio
from copy import deepcopy
from dataclasses import asdict, fields, replace
from contextlib import asynccontextmanager

from .errors import SDKError, StaleContextError
from .providers import (
    ConnectionResult,
    ModelChunk,
    ModelRequest,
    ModelToolChoice,
    ProviderContext,
)
from .storage import PluginConfig


# Keep the ownership state machine in one scope.
# pylint: disable-next=too-many-statements
def register(context, spec):
    from agentscope.credential import CredentialBase
    from agentscope.formatter import OpenAIChatFormatter
    from agentscope.model import ChatModelBase
    from ..providers.provider import Provider
    from ..providers.model_info import ModelInfo
    from ._messages import from_host
    from ._models import ModelAccumulator, model_response

    admitted = True

    def guard():
        context._guard()
        if not admitted:
            raise StaleContextError(f"Provider {spec.id!r} has been released")

    @asynccontextmanager
    async def invocation(provider, deadline=None):
        from ..config.context import get_current_session_id
        from ._workspace import current_workspace_id

        guard()
        async with context._invocation(
            workspace_id=current_workspace_id(),
            session_id=get_current_session_id() or "",
            deadline=deadline,
        ) as base:
            values = dict(context._api.config)
            values["api_key"] = provider.api_key
            secrets = [
                "api_key",
                *(context._api.manifest.get("sdk") or {}).get("secrets", []),
            ]
            public = ProviderContext(
                **{
                    field.name: getattr(base, field.name)
                    for field in fields(base)
                },
                provider_id=spec.id,
                base_url=provider.base_url,
                headers=deepcopy(provider.custom_headers),
            )
            yield replace(
                public,
                config=PluginConfig(values, {"secrets": secrets}),
            )

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
        @classmethod
        def get_default_models(cls):
            return [ModelInfo(**asdict(item)) for item in spec.models]

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
                return [ModelInfo(**asdict(item)) for item in result]

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
    )
    from .resources import Registration

    async def release():
        nonlocal admitted
        admitted = False
        await handle.close()

    return Registration(
        release,
        owner=context.resources.owner,
        description=f"provider:{spec.id}",
    )
