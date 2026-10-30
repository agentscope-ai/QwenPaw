# -*- coding: utf-8 -*-
"""Native Provider requests use the existing transport and scoped SDK state."""
# pylint: disable=protected-access

import asyncio
import json

import httpx
import pytest
from agentscope.message import Msg
from agentscope.tool import ToolChoice
from openai import AsyncOpenAI, InternalServerError

from qwenpaw.plugins import SDKError, StaleContextError
from qwenpaw.plugins._providers import ProviderTurn
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_manager import ProviderManager

from .sdk_author_fixture import make_plugin


SOURCE = """
from contextlib import asynccontextmanager
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo

class Plugin:
    def register(self, ctx):
        self.ctx = ctx
        self.active = 0
        self.calls = 0
        self.provider = ctx.register_provider(ProviderSpec(
            id="native-test", label="Native test", protocol="openai-chat",
            base_url="https://configured.test/v1", require_api_key=False,
            models=(ModelInfo("model-A", "A", supports_multimodal=False),),
            connect=self.connect if ctx.config.get("prepare", True) else None,
        ))

    @asynccontextmanager
    async def connect(self, call, model_id):
        assert call.provider_id == "native-test"
        assert model_id == "model-A"
        assert not hasattr(call, "workspace")
        self.calls += 1
        self.active += 1
        try:
            yield "https://prepared.test/v1"
        finally:
            self.active -= 1

plugin = Plugin()
"""


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("prepare", [True, False])
async def test_native_wire_request_and_response_match_host(
    tmp_path,
    streaming,
    prepare,
):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test"
        assert request.headers["x-provider-test"] == "preserved"
        requests.append((request.url, body))
        base = {"id": "reply", "created": 0, "model": "model-A"}
        usage = {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        }
        if body["stream"]:
            chunks = [
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "OK"},
                            "finish_reason": None,
                        },
                    ],
                },
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        },
                    ],
                    "usage": usage,
                },
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"data: {json.dumps(chunk)}\n\n" for chunk in chunks
                )
                + "data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                **base,
                "object": "chat.completion",
                "usage": usage,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "OK",
                        },
                    },
                ],
            },
        )

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(
                tmp_path,
                SOURCE,
                ["providers", "resources", "config"],
            ),
            config={"prepare": prepare},
        )
        manager = ProviderManager.get_instance()
        await manager.update_provider_async(
            "native-test",
            {
                "api_key": "test",
                "custom_headers": {"X-Provider-Test": "preserved"},
            },
        )
        provider = manager.get_provider("native-test")
        model = provider.get_chat_model_instance("model-A")
        baseline = OpenAIProvider(
            **provider.model_dump(),
        ).get_chat_model_instance("model-A")
        assert type(model.formatter) is type(baseline.formatter)
        outputs = []
        for current in (baseline, model):
            await current.client.close()
            current.stream = streaming
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond),
            ) as http:
                current.client = current.client.with_options(http_client=http)
                result = await current(
                    [
                        Msg(
                            name="user",
                            role="user",
                            content=[{"type": "text", "text": "hello"}],
                        ),
                    ],
                    temperature=0.25,
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "description": "Lookup",
                                "parameters": {
                                    "type": "object",
                                    "properties": {},
                                },
                            },
                        },
                    ],
                    tool_choice=ToolChoice(mode="auto"),
                )
                if streaming:
                    try:
                        parts = [part async for part in result]
                    finally:
                        await result.aclose()
                    result = parts[-1]
                content = [
                    block.model_dump(
                        exclude={"id", "created_at", "finished_at"},
                    )
                    for block in result.content
                ]
                outputs.append(
                    (
                        content,
                        result.usage.input_tokens,
                        result.usage.output_tokens,
                    ),
                )
                assert (
                    str(current.client.base_url)
                    == "https://configured.test/v1/"
                )
                assert current.client.api_key == "test"
        assert outputs[0] == outputs[1]
        assert outputs[1][1:] == (12, 3)
        assert requests[0][1] == requests[1][1]
        assert requests[1][0].host == (
            "prepared.test" if prepare else "configured.test"
        )
        assert requests[1][0].path == "/v1/chat/completions"
        assert requests[1][1]["tools"][0]["function"]["name"] == "lookup"
        assert requests[1][1]["tool_choice"] == "auto"
        assert provider.api_key == "test"
        assert provider.custom_headers == {"X-Provider-Test": "preserved"}


@pytest.mark.parametrize("prepare", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_native_http_failure_releases_use_and_allows_retry(
    tmp_path,
    prepare,
    streaming,
):
    attempts = []

    def respond(request):
        attempts.append(request.url)
        if len(attempts) == 1:
            return httpx.Response(
                500,
                json={"error": {"message": "unavailable"}},
            )
        return httpx.Response(
            200,
            json={
                "id": "retry",
                "created": 0,
                "model": "model-A",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "recovered",
                        },
                    },
                ],
            },
        )

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(
                tmp_path,
                SOURCE,
                ["providers", "resources", "config"],
            ),
            config={"prepare": prepare},
        )
        provider = ProviderManager.get_instance().get_provider("native-test")
        model = provider.get_chat_model_instance("model-A")
        await model.client.close()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ) as http:
            model.client = AsyncOpenAI(
                api_key="test",
                base_url=provider.base_url,
                http_client=http,
                max_retries=0,
            )
            model.stream = streaming
            model.max_retries = 0
            messages = [
                Msg(
                    name="user",
                    role="user",
                    content=[{"type": "text", "text": "hello"}],
                ),
            ]
            with pytest.raises(InternalServerError):
                response = await model(messages)
                if streaming:
                    try:
                        await anext(response)
                    finally:
                        await response.aclose()
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )
            model.stream = False
            result = await model(messages)
            assert result.content[0].text == "recovered"
            assert len(attempts) == 2


@pytest.mark.parametrize("prepare", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_native_cancel_during_http_request_releases_use(
    tmp_path,
    prepare,
    streaming,
):
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def respond(_request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(
                tmp_path,
                SOURCE,
                ["providers", "resources", "config"],
            ),
            config={"prepare": prepare},
        )
        provider = ProviderManager.get_instance().get_provider("native-test")
        model = provider.get_chat_model_instance("model-A")
        await model.client.close()
        model.stream = streaming
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ) as http:
            model.client = AsyncOpenAI(
                api_key="test",
                base_url=provider.base_url,
                http_client=http,
                max_retries=0,
            )

            async def consume():
                response = await model(
                    [
                        Msg(
                            name="user",
                            role="user",
                            content=[{"type": "text", "text": "hello"}],
                        ),
                    ],
                )
                if streaming:
                    try:
                        async for _ in response:
                            pass
                    finally:
                        await response.aclose()

                return response

            task = asyncio.create_task(consume())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                if streaming:
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 2)
                else:
                    result = await asyncio.wait_for(task, 2)
                    assert result.finished_reason == "interrupted"
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            assert stopped.is_set()
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )


async def test_provider_handle_is_scoped_persistent_and_revoked(tmp_path):
    from qwenpaw.plugins.providers import ModelInfo

    async with PluginTestHost(tmp_path / "host") as host:
        path = make_plugin(tmp_path, SOURCE, ["providers", "resources"])
        await host.load(path)
        binding = (
            PluginRegistry()
            .get_provider("native-test")
            .provider_class._sdk_binding
        )
        handle = binding.spec.connect.__self__.provider
        await handle.update(
            models=(ModelInfo("model-B", "B", supports_multimodal=False),),
            generate_kwargs={"temperature": 0.4},
        )
        manager = ProviderManager.get_instance()
        await handle.select("model-B")
        assert manager.active_model.provider_id == "native-test"
        assert manager.active_model.model == "model-B"
        assert manager.load_active_model() == manager.active_model
        assert (await host.reload("extension-contract")).ok
        provider = manager.get_provider("native-test")
        assert provider.generate_kwargs == {"temperature": 0.4}
        assert provider.extra_models[0].id == "model-B"
        with pytest.raises(StaleContextError):
            await handle.update(base_url="https://stale.test")
        with pytest.raises(StaleContextError):
            await handle.clear_selection()
        with pytest.raises(StaleContextError):
            await handle.select("model-B")


@pytest.mark.parametrize("native", [False, True])
async def test_provider_selection_is_scoped_and_preserves_other_defaults(
    tmp_path,
    native,
):
    from qwenpaw.providers.provider_manager import ModelSlotConfig
    from qwenpaw.config.config import (
        AgentProfileConfig,
        AgentProfileRef,
        save_agent_config,
    )
    from qwenpaw.config.utils import mutate_config

    source = SOURCE
    if not native:
        source = source.replace(
            'protocol="openai-chat",',
            "generate=lambda ctx, req: None,",
        ).replace(
            'connect=self.connect if ctx.config.get("prepare", True) '
            "else None,",
            "",
        )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["providers", "resources"]),
        )
        handle = host._loader.get_loaded_plugin(
            "extension-contract",
        ).instance.provider
        manager = ProviderManager.get_instance()
        selected = ModelSlotConfig(provider_id="native-test", model="model-A")
        await handle.select("model-A")
        assert manager.active_model == selected
        assert manager.load_active_model() == selected
        await manager.save_active_model_async(selected, model_type="embedding")
        agent_dir = tmp_path / "host/workspaces/independent"
        mutate_config(
            lambda root: root.agents.profiles.update(
                {
                    "independent": AgentProfileRef(
                        id="independent",
                        workspace_dir=str(agent_dir),
                    ),
                },
            ),
        )
        save_agent_config(
            "independent",
            AgentProfileConfig(
                id="independent",
                name="Independent",
                active_model=selected.model_dump(),
            ),
        )
        agent_path = agent_dir / "agent.json"
        agent_before = agent_path.read_bytes()
        assert await handle.clear_selection()
        assert manager.active_model is None
        assert manager.load_active_model() is None
        assert manager.default_models["embedding"] == selected
        assert agent_path.read_bytes() == agent_before
        assert not await handle.clear_selection()

        cloud = ModelSlotConfig(provider_id="openai", model="cloud")
        await manager.save_active_model_async(cloud)
        assert not await handle.clear_selection()
        assert manager.active_model == cloud
        assert manager.load_active_model() == cloud
        with pytest.raises(SDKError):
            await handle.select("missing-model")
        assert manager.active_model == cloud
        assert manager.load_active_model() == cloud


async def test_preparation_is_per_call_and_release_is_per_turn(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, SOURCE, ["providers", "resources"]),
        )
        binding = (
            PluginRegistry()
            .get_provider("native-test")
            .provider_class._sdk_binding
        )
        plugin = binding.spec.connect.__self__
        for _ in range(2):
            turn = ProviderTurn()
            try:
                for _ in range(3):
                    async with binding.connect("model-A") as endpoint:
                        assert endpoint == "https://prepared.test/v1"
                assert plugin.active == 3
            finally:
                await turn.close()
            assert plugin.active == 0
        assert plugin.calls == 6


async def test_concurrent_native_calls_keep_their_own_endpoint(tmp_path):
    source = SOURCE.replace(
        'yield "https://prepared.test/v1"',
        'yield f"https://prepared-{self.calls}.test/v1"',
    )
    arrived = []
    both = asyncio.Event()

    async def respond(request):
        arrived.append(request.url.host)
        if len(arrived) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 2)
        return httpx.Response(
            200,
            json={
                "id": "reply",
                "created": 0,
                "model": "model-A",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "OK",
                        },
                    },
                ],
            },
        )

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["providers", "resources"]),
        )
        provider = ProviderManager.get_instance().get_provider("native-test")
        model = provider.get_chat_model_instance("model-A")
        await model.client.close()
        model.stream = False
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ) as http:
            model.client = AsyncOpenAI(
                api_key="test",
                base_url=provider.base_url,
                http_client=http,
            )
            await asyncio.gather(
                *[
                    model(
                        [
                            Msg(
                                name="user",
                                role="user",
                                content=[{"type": "text", "text": "hello"}],
                            ),
                        ],
                    )
                    for _ in range(2)
                ],
            )
            assert sorted(arrived) == ["prepared-1.test", "prepared-2.test"]
            assert str(model.client.base_url) == "https://configured.test/v1/"


@pytest.mark.parametrize(
    "operation",
    ["check_model_connection", "probe_model_multimodal"],
)
async def test_native_probes_use_prepared_endpoint_and_release_it(
    tmp_path,
    monkeypatch,
    operation,
):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, SOURCE, ["providers", "resources"]),
        )
        await ProviderManager.get_instance().update_provider_async(
            "native-test",
            {
                "api_key": "configured",
                "custom_headers": {
                    "X-Provider-Test": "configured",
                    "x-preserved": "configured",
                },
            },
        )
        provider = ProviderManager.get_instance().get_provider("native-test")
        plugin = provider._sdk_binding.spec.connect.__self__
        result = object()

        async def probe(current, model_id, timeout, **kwargs):
            assert current.base_url == "https://prepared.test/v1"
            assert current.api_key == "configured"
            assert (
                httpx.Headers(current.custom_headers)["x-provider-test"]
                == "configured"
            )
            assert current.custom_headers["x-preserved"] == "configured"
            assert model_id == "model-A" and timeout == 3
            assert plugin.active == 1
            assert kwargs == (
                {"image_only": False}
                if operation == "probe_model_multimodal"
                else {}
            )
            return result

        monkeypatch.setattr(OpenAIProvider, operation, probe)
        assert (
            await getattr(provider, operation)("model-A", timeout=3) is result
        )
        assert plugin.active == 0
        assert provider.base_url == "https://configured.test/v1"
        assert provider.api_key == "configured"
        assert provider.custom_headers["X-Provider-Test"] == "configured"


@pytest.mark.parametrize(
    "failure",
    ["FileNotFoundError('model missing')", "RuntimeError('runtime missing')"],
)
async def test_endpoint_failure_returns_model_check_result(tmp_path, failure):
    from fastapi import FastAPI
    from qwenpaw.app.routers import providers as routes

    source = SOURCE.replace("self.calls += 1", f"raise {failure}")
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["providers"]))
        manager = ProviderManager.get_instance()
        result = await manager.check_provider_model("native-test", "model-A")
        assert not result.success
        assert result.verification == "unverified"
        reason = (
            "model missing" if "FileNotFound" in failure else "runtime missing"
        )
        assert reason in result.message
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        app.dependency_overrides[routes.get_provider_manager] = lambda: manager
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/models/native-test/models/test",
                json={"model_id": "model-A"},
            )
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["verification"] == "unverified"
        assert reason in response.json()["message"]
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


async def test_endpoint_check_cancellation_propagates(tmp_path):
    source = "import asyncio\n" + SOURCE.replace(
        "self.calls += 1",
        "raise asyncio.CancelledError()",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["providers"]))
        with pytest.raises(asyncio.CancelledError):
            await ProviderManager.get_instance().check_provider_model(
                "native-test",
                "model-A",
            )
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


@pytest.mark.parametrize("provider_id", ["openai", "dashscope"])
async def test_plugin_cannot_replace_an_unowned_builtin(tmp_path, provider_id):
    source = SOURCE.replace('id="native-test"', f'id="{provider_id}"')
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError, match="already|conflict|exists|collid"):
            await host.load(
                make_plugin(tmp_path, source, ["providers", "resources"]),
            )


@pytest.mark.parametrize("provider_id", ["qwenpaw-local", "COPAW-LOCAL"])
async def test_plugin_provider_uses_canonical_config(tmp_path, provider_id):
    async with PluginTestHost(tmp_path / "host"):
        manager = ProviderManager.get_instance()
        await manager.register_plugin_provider_async(
            "qwenpaw-local",
            OpenAIProvider,
            "Local",
            "",
            metadata={},
        )
        await manager.update_provider_async(
            provider_id,
            {"generate_kwargs": {"temperature": 0.4}},
        )
        path = manager._provider_config_path(provider_id)
        assert path == manager.plugin_path / "qwenpaw-local.json"
        manager.unregister_plugin_provider(provider_id)
        assert manager.get_provider(provider_id) is None
        await manager.register_plugin_provider_async(
            "qwenpaw-local",
            OpenAIProvider,
            "Local",
            "",
            metadata={},
        )
        provider = manager.get_provider(provider_id)
        assert provider.id == "qwenpaw-local"
        assert provider.generate_kwargs == {"temperature": 0.4}
        assert manager._provider_config_path(provider_id) == path
        manager.unregister_plugin_provider(provider_id)


@pytest.mark.parametrize(
    "declaration",
    [
        'ProviderSpec("broken", "Broken")',
        'ProviderSpec("broken", "Broken", protocol="unknown")',
        'ProviderSpec("broken", "Broken", generate=lambda *a: None, '
        'protocol="openai-chat")',
        'ProviderSpec("broken", "Broken", generate=lambda *a: None, '
        "connect=lambda *a: None)",
    ],
)
async def test_invalid_provider_contract_is_rejected(tmp_path, declaration):
    source = f"""from qwenpaw.plugins.providers import ProviderSpec
class Plugin:
    def register(self, ctx):
        ctx.register_provider({declaration})
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError):
            await host.load(make_plugin(tmp_path, source, ["providers"]))


@pytest.mark.parametrize(
    "endpoint",
    ['""', "123"],
)
async def test_invalid_endpoint_releases_usage(tmp_path, endpoint):
    source = f"""
from contextlib import asynccontextmanager
from qwenpaw.plugins.providers import ProviderSpec

class Plugin:
    def register(self, ctx):
        @asynccontextmanager
        async def connect(call, model_id):
            try:
                yield {endpoint}
            finally:
                ctx.storage.write_json("closed.json", True)

        ctx.register_provider(ProviderSpec(
            "invalid-connection", "Invalid connection",
            protocol="openai-chat", connect=connect,
        ))

plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["providers", "storage"]),
        )
        provider = ProviderManager.get_instance().get_provider(
            "invalid-connection",
        )
        with pytest.raises(SDKError, match="nonempty base URL"):
            async with provider._sdk_binding.connect("model-A"):
                pytest.fail("An invalid connection must not be used")
        assert ctx.storage.read_json("closed.json") is True
        assert host.resource_snapshot(ctx.plugin_id)["active_calls"] == 0
