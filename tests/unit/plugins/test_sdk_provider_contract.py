# -*- coding: utf-8 -*-
"""Public provider contracts through the production model factory."""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
    ModelUsage,
)
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            assert not hasattr(call, "workspace") and not hasattr(
                call, "agent"
            )
            ctx.storage.write_json(
                "request.json",
                {
                    "provider": call.provider_id,
                    "workspace": call.workspace_id,
                    "session": call.session_id,
                    "model": request.model_id,
                    "text": request.messages[0].content[0].text,
                    "tools": list(request.tools),
                    "options": request.options,
                    "choice": (
                        request.tool_choice.mode
                        if request.tool_choice
                        else None
                    ),
                },
            )
            try:
                yield ModelChunk(
                    (ContentBlock(type="thinking", text="reason"),),
                    id="response-1",
                )
                yield ModelChunk(
                    (
                        ContentBlock(
                            type="tool_call",
                            id="call-1",
                            name="calculate",
                            arguments='{"x":3}',
                        ),
                    ),
                    id="response-1",
                )
                yield ModelChunk(
                    (ContentBlock(text="answer"),),
                    is_last=True,
                    usage=ModelUsage(12, 3),
                    id="response-1",
                    metadata={"finish": "ok"},
                )
            finally:
                ctx.storage.write_json("closed.json", True)

        ctx.register_provider(
            ProviderSpec(
                "sdk-provider",
                "SDK Provider",
                generate,
                models=(ModelInfo("sdk-model", "SDK model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""


async def test_provider_preserves_public_request_and_multiblock_response(
    tmp_path,
):
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.providers import ModelToolChoice
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["providers", "storage"]),
        )
        assert (await host.discover_models("sdk-provider"))[
            0
        ].id == "sdk-model"
        model = await host.create_model(
            "sdk-provider",
            "sdk-model",
            workspace_id="one",
        )
        tool = {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "calculate",
                "parameters": {"type": "object"},
            },
        }
        chunks = [
            chunk
            async for chunk in model.stream(
                (Message("user", (ContentBlock(text="question"),)),),
                tools=(tool,),
                tool_choice=ModelToolChoice("auto"),
                options={"temperature": 0.2},
                session_id="conversation",
            )
        ]
        content = [block for chunk in chunks for block in chunk.content]
        assert [block.type for block in content] == [
            "thinking",
            "tool_call",
            "text",
        ]
        assert content[1].id == "call-1" and content[1].arguments == '{"x":3}'
        assert [chunk.is_last for chunk in chunks] == [False] * (
            len(chunks) - 1
        ) + [
            True,
        ]
        assert content[0].text == "reason" and content[2].text == "answer"
        assert (
            chunks[-1].usage.input_tokens == 12
            and chunks[-1].usage.output_tokens == 3
        )
        assert chunks[-1].metadata == {"finish": "ok"}
        request = ctx.storage.read_json("request.json")
        assert request == {
            "provider": "sdk-provider",
            "workspace": "one",
            "session": "conversation",
            "model": "sdk-model",
            "text": "question",
            "tools": [tool],
            "options": {"temperature": 0.2},
            "choice": "auto",
        }
        assert ctx.storage.read_json("closed.json") is True
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


async def test_provider_cross_task_stream_keeps_owner_busy_and_closes(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError, StaleContextError
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["providers", "storage"]),
        )
        model = await host.create_model("sdk-provider", "sdk-model")
        stream = model.stream(
            (Message("user", (ContentBlock(text="question"),)),),
        )
        first = asyncio.create_task(anext(stream))
        await first
        try:
            assert first.done()
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                > 0
            )
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        finally:
            await stream.aclose()
        assert ctx.storage.read_json("closed.json") is True
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )
        assert (await host.reload("extension-contract")).ok
        stale_stream = model.stream(
            (Message("user", (ContentBlock(text="question"),)),),
        )
        with pytest.raises(StaleContextError):
            await anext(stale_stream)
        await stale_stream.aclose()


@pytest.mark.parametrize("case", ["missing_terminal", "after_terminal"])
async def test_provider_rejects_invalid_stream_terminal_protocol(
    tmp_path,
    case,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            yield ModelChunk(
                (ContentBlock(text="first"),),
                is_last=ctx.config.get("case") == "after_terminal",
            )
            if ctx.config.get("case") == "after_terminal":
                yield ModelChunk(
                    (ContentBlock(text="illegal trailing data"),)
                )

        ctx.register_provider(
            ProviderSpec(
                "sdk-provider",
                "SDK Provider",
                generate,
                models=(ModelInfo("sdk-model", "SDK model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["providers", "config"]),
            config={"case": case},
        )
        model = await host.create_model("sdk-provider", "sdk-model")
        with pytest.raises(SDKError, match="terminal"):
            async for _ in model.stream(
                (Message("user", (ContentBlock(text="question"),)),),
            ):
                pass
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


async def test_provider_configuration_uses_secret_api_and_survives_reload(
    tmp_path,
):
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins import SDKError


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            assert (
                call.config.secret("api_key")
                == "test-only-provider-key"
            )
            try:
                call.config.get("api_key")
            except SDKError:
                pass
            else:
                raise AssertionError("secret exposed by get")
            assert (
                call.base_url == "https://sdk-provider.example.test"
            )
            assert request.options["temperature"] == 0.4
            yield ModelChunk(
                (ContentBlock(text="configured"),), is_last=True
            )

        ctx.register_provider(
            ProviderSpec(
                "sdk-provider",
                "SDK Provider",
                generate,
                models=(ModelInfo("sdk-model", "SDK model"),),
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["providers", "config"]))
        await host.configure_provider(
            "sdk-provider",
            api_key="test-only-provider-key",
            base_url="https://sdk-provider.example.test",
            options={"temperature": 0.4},
        )
        for index in range(2):
            if index:
                assert (await host.reload("extension-contract")).ok
            model = await host.create_model("sdk-provider", "sdk-model")
            chunks = [
                chunk
                async for chunk in model.stream(
                    (Message("user", (ContentBlock(text="question"),)),),
                )
            ]
            assert (
                "".join(
                    block.text for chunk in chunks for block in chunk.content
                )
                == "configured"
            )
