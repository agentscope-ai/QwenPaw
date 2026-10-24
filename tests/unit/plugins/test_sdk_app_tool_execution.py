# -*- coding: utf-8 -*-
"""Real model/tool coordinator round trips and scoped cancellation."""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
import asyncio
import json
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, plugin):
        async def tool(call, arguments):
            owner = arguments["owner"]
            key = f"entered-{owner}.json"
            plugin.storage.write_json(
                key, plugin.storage.read_json(key, 0) + 1
            )
            try:
                while not (
                    Path(plugin.config.get("directory"))
                    / f"release-{owner}"
                ).exists():
                    await asyncio.sleep(0.01)
                return ToolResult.text("tool-completed:" + owner)
            finally:
                plugin.storage.write_json(
                    f"stopped-{owner}.json", True
                )

        async def generate(call, request):
            texts = [
                block.text
                for message in request.messages
                if message.role == "user"
                for block in message.content
            ]
            owner = (
                "alice"
                if any("owner-alice" in text for text in texts)
                else "bob"
            )
            results = [
                block
                for message in request.messages
                for block in message.content
                if block.type == "tool_result"
            ]
            if results:
                plugin.storage.write_json(
                    f"model-result-{owner}.json",
                    [str(block.output) for block in results],
                )
                yield ModelChunk(
                    (ContentBlock(text="finished:" + owner),),
                    is_last=True,
                )
            else:
                assert any(
                    item.get("function", {}).get("name")
                    == "app_wait_tool"
                    for item in request.tools
                )
                yield ModelChunk(
                    (
                        ContentBlock(
                            type="tool_call",
                            id="call-" + owner,
                            name="app_wait_tool",
                            arguments='{"owner":',
                        ),
                    ),
                    id="answer-" + owner,
                )
                yield ModelChunk(
                    (
                        ContentBlock(
                            type="tool_call",
                            id="call-" + owner,
                            arguments=json.dumps(owner) + "}",
                        ),
                    ),
                    id="answer-" + owner,
                )
                yield ModelChunk(
                    (), is_last=True, id="answer-" + owner
                )

        plugin.register_tool(
            ToolSpec(
                "app_wait_tool",
                "Wait for test release",
                {
                    "type": "object",
                    "properties": {
                        "owner": {
                            "type": "string",
                            "enum": ["alice", "bob"],
                        }
                    },
                    "required": ["owner"],
                },
                tool,
                enabled=True,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "app-test-provider",
                "App test model",
                generate,
                models=(ModelInfo("test-model", "Test model"),),
                require_api_key=False,
            )
        )
        plugin.register_app(
            PawApp(app_id="tool-app").enable_standard_capabilities()
        )


plugin = Plugin()
"""


async def wait_value(ctx, key):
    for _ in range(300):
        value = ctx.storage.read_json(key, None)
        if value is not None:
            return value
        await asyncio.sleep(0.01)
    pytest.fail(f"Runtime did not produce {key}")


async def test_app_cancel_preserves_other_users_real_tool_and_model_roundtrip(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                SOURCE,
                ["apps", "providers", "tools", "storage", "config"],
            ),
            config={"directory": str(tmp_path)},
        )
        await host.configure_chat_model("app-test-provider", "test-model")
        tasks = {}
        try:
            for user in ("alice", "bob"):
                response = await host.request(
                    "POST",
                    "/api/tool-app/tasks",
                    user_id=user,
                    json={
                        "message": "owner-" + user,
                        "session_id": "same-suffix",
                    },
                )
                assert response.status == 200
                tasks[user] = response.json()
            assert tasks["alice"]["session_id"] != tasks["bob"]["session_id"]
            for user in tasks:
                assert await wait_value(ctx, f"entered-{user}.json") == 1
            cancelled = await host.request(
                "POST",
                f'/api/tool-app/tasks/{tasks["alice"]["run_id"]}/cancel',
                user_id="alice",
            )
            assert (
                cancelled.status == 200 and cancelled.json()["stopped"] is True
            )
            assert await wait_value(ctx, "stopped-alice.json") is True
            assert ctx.storage.read_json("stopped-bob.json", False) is False
            bob = await host.request(
                "GET",
                f'/api/tool-app/tasks/{tasks["bob"]["run_id"]}',
                user_id="bob",
            )
            assert bob.json()["status"] == "running"
            (tmp_path / "release-bob").touch()
            results = await wait_value(ctx, "model-result-bob.json")
            assert len(results) == 1 and "tool-completed:bob" in results[0]
            for _ in range(200):
                bob = await host.request(
                    "GET",
                    f'/api/tool-app/tasks/{tasks["bob"]["run_id"]}',
                    user_id="bob",
                )
                if bob.json()["status"] != "running":
                    break
                await asyncio.sleep(0.01)
            assert bob.json()["status"] == "completed"
            assert ctx.storage.read_json("entered-bob.json") == 1
        finally:
            for user in ("alice", "bob"):
                (tmp_path / f"release-{user}").touch()
            for _ in range(300):
                if (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    == 0
                ):
                    break
                await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "schema",
    [{"type": "object"}, {"type": "object", "properties": {}}],
)
async def test_model_media_and_metadata_survive_history_reload(
    tmp_path,
    schema,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import base64
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, plugin):
        async def image(call, arguments):
            plugin.storage.write_json(
                "tool-calls.json",
                plugin.storage.read_json("tool-calls.json", 0) + 1,
            )
            attachment = call.media.write(
                "model-history.png",
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91Jpz"
                    "AAAAEklEQVR4nGM84SbHwMDAxAAGAA7kATAvGkgcAAAAAElFTkSuQmCC"
                ),
                mime_type="image/png",
            )
            plugin.storage.write_json(
                "preview.json", attachment.preview_url
            )
            return ToolResult(
                (ContentBlock("image", attachment=attachment),),
                metadata={
                    "_sdk_event": "author",
                    "is_error": "author",
                    "_sdk_author_metadata": ["author"],
                    "_sdk_attachment_previews": {"refs": {}},
                },
            )

        async def generate(call, request):
            results = [
                block
                for message in request.messages
                for block in message.content
                if block.type == "tool_result"
                and block.name == "history_image"
            ]
            if results:
                records = plugin.storage.read_json(
                    "received.json", []
                )
                records.append(
                    {
                        "metadata": results[0].metadata,
                        "preview": next(
                            (
                                block.attachment.preview_url
                                for block in results[0].output
                                if block.attachment
                            ),
                            None,
                        ),
                        "output": [
                            {
                                "type": block.type,
                                "id": block.id,
                                "text": block.text,
                                "url_scheme": (
                                    block.attachment.url.partition(
                                        ":"
                                    )[0]
                                    if block.attachment
                                    else None
                                ),
                            }
                            for block in results[0].output
                        ],
                    }
                )
                plugin.storage.write_json("received.json", records)
                yield ModelChunk(
                    (ContentBlock(text="image received"),),
                    is_last=True,
                )
            else:
                yield ModelChunk(
                    (
                        ContentBlock(
                            "tool_call",
                            id="image-call",
                            name="history_image",
                            arguments="{}",
                        ),
                    ),
                    is_last=True,
                )

        plugin.register_tool(
            ToolSpec(
                "history_image",
                "image",
                {"type": "object"},
                image,
                enabled=True,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "image-provider",
                "Image provider",
                generate,
                models=(ModelInfo("image-model", "Image model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    source = source.replace('{"type": "object"}', repr(schema))
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["tools", "providers", "storage"]),
        )
        await host.configure_chat_model("image-provider", "image-model")
        for text in ("generate image", "use the previous image"):
            events = [
                event
                async for event in host.stream_chat(
                    text,
                    session_id="image-history",
                )
            ]
            assert any(
                event.object == "response" and event.status == "completed"
                for event in events
            )
            assert (await host.reload("extension-contract")).ok
            ctx = host.context("extension-contract")
        records = ctx.storage.read_json("received.json")
        assert ctx.storage.read_json("tool-calls.json") == 1, records
        assert len(records) == 2
        for record in records:
            assert record["metadata"] == {
                "_sdk_event": "author",
                "is_error": "author",
                "_sdk_author_metadata": ["author"],
                "_sdk_attachment_previews": {"refs": {}},
            }
            assert record["preview"] == ctx.storage.read_json("preview.json")
            assert record["preview"].startswith("/api/files/preview/")
        host.assert_quiescent("extension-contract")
