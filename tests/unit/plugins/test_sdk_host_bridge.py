# -*- coding: utf-8 -*-
"""Host-side checks of public SDK contributions in the actual tool bridge."""

import asyncio
import os

import pytest

from .test_sdk_author_host import make_plugin
from .test_sdk_entry_contract import write_plugin

from .timing import WAIT_TIMEOUT, wait_for_thread_progress


async def test_published_runtime_tool_stream_remains_busy_until_closed(
    tmp_path,
):
    from qwenpaw.agents import tools
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path),
            config={"marker": str(tmp_path / "closed")},
        )
        invoke = getattr(tools, "sdk_contract_stream")
        stream = invoke()
        try:
            response = await asyncio.create_task(anext(stream))
            assert [
                (block.type, block.text) for block in response.content
            ] == [
                ("text", "first"),
            ]
            with pytest.raises(PluginBusyError):
                await host.reload("author-contract")
        finally:
            await stream.aclose()
        assert (tmp_path / "closed").read_text() == "stream-closed"
        assert host.resource_snapshot("author-contract")["active_calls"] == 0
        assert (await host.reload("author-contract")).ok


async def test_function_tool_stream_close_releases_sdk_invocation(tmp_path):
    from qwenpaw.agents import tools
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path),
            config={"marker": str(tmp_path / "closed")},
        )
        tool = GuardedFunctionTool(getattr(tools, "sdk_contract_stream"))
        stream = await tool.call()
        try:
            response = await anext(stream)
            assert response.content[0].text == "first"
        finally:
            await stream.aclose()
        assert (tmp_path / "closed").exists()
        assert host.resource_snapshot("author-contract")["active_calls"] == 0
        assert (await host.reload("author-contract")).ok


async def test_retained_old_handle_cannot_remove_replacement_tool(
    tmp_path,
):  # pylint: disable=protected-access
    from qwenpaw.agents import tools
    from qwenpaw.plugins import StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path))
        # Retain the exact handle returned during old-plugin registration.
        old_handle = ctx._tools["sdk_contract_echo"][1]
        previous = getattr(tools, "sdk_contract_echo")
        assert (await host.reload("author-contract")).ok
        current = getattr(tools, "sdk_contract_echo")
        assert current is not previous
        stale_stream = previous(text="stale invocation")
        try:
            with pytest.raises(StaleContextError):
                await anext(stale_stream)
        finally:
            await stale_stream.aclose()
        await old_handle.close()
        await old_handle.close()
        assert getattr(tools, "sdk_contract_echo") is current
        result = await host.call_tool(
            "sdk_contract_echo",
            {"text": "new generation"},
        )
        assert result.content[0].text == "new generation"


async def test_error_result_retains_error_terminal_state_in_runtime(tmp_path):
    from agentscope.message import ToolResultState
    from qwenpaw.agents import tools
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    source = """
from qwenpaw.plugins.tools import ToolResult, ToolSpec
class Plugin:
    def register(self, ctx):
        async def fail(call, arguments):
            return ToolResult.text("remote operation failed", is_error=True)
        ctx.register_tool(ToolSpec(
            name="sdk_terminal_failure", description="A failed operation",
            input_schema={"type": "object"}, handler=fail, enabled=True,
        ))
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        tool = GuardedFunctionTool(getattr(tools, "sdk_terminal_failure"))
        stream = await tool.call()
        chunks = [chunk async for chunk in stream]
        assert chunks[-1].is_last
        assert chunks[-1].state is ToolResultState.ERROR
        assert all(
            chunk.state is not ToolResultState.SUCCESS for chunk in chunks
        )
        assert any(
            block.text == "remote operation failed"
            for chunk in chunks
            for block in chunk.content
        )


async def test_host_does_not_reuse_preexisting_config_cache(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.config import utils
    from qwenpaw.config.config import Config
    from qwenpaw.plugins.testing import PluginTestHost

    outside, inside = tmp_path / "outside", tmp_path / "host"
    outside.mkdir()
    inside.mkdir()
    monkeypatch.setattr(utils, "WORKING_DIR", outside)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    utils.save_config(Config(plugins={"outside-marker": {}}))
    path = inside / "config.json"
    path.write_text(
        Config(plugins={"inside-marker": {}}).model_dump_json(),
        encoding="utf-8",
    )
    mtime = (outside / "config.json").stat().st_mtime_ns
    os.utime(path, ns=(mtime, mtime))
    assert "outside-marker" in utils.load_config().plugins
    async with PluginTestHost(inside):
        assert set(utils.load_config().plugins) == {"inside-marker"}
    assert set(utils.load_config().plugins) == {"outside-marker"}


async def test_config_replacement_invalidates_old_context_and_tool_handles(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
):
    from qwenpaw.agents import tools
    from qwenpaw.plugins import StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        old = await host.load(make_plugin(tmp_path))
        handle = old._tools["sdk_contract_echo"][1]
        report = await host._loader.lifecycle.update_config(
            "author-contract",
            {"changed": True},
        )
        assert report.ok, report.errors
        owner = host.context("author-contract").resources.owner
        assert owner.plugin_id == old.resources.owner.plugin_id
        assert owner != old.resources.owner
        current = getattr(tools, "sdk_contract_echo")
        with pytest.raises(StaleContextError):
            old.storage.write_json("stale.json", {"write": "must be rejected"})
        await handle.close()
        assert getattr(tools, "sdk_contract_echo") is current
        assert (
            await host.call_tool("sdk_contract_echo", {"text": "current"})
        ).content[0].text == "current"


async def test_old_activation_handle_cannot_unregister_reloaded_hook(
    tmp_path,
):  # pylint: disable=protected-access
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
class Plugin:
    def register(self, ctx):
        self.handle = ctx.on_activate(lambda context: None)
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        old = host._loader.get_loaded_plugin("author-contract").instance.handle
        assert (await host.reload("author-contract")).ok
        current_hooks = host._loader.registry.get_startup_hooks()
        assert len(current_hooks) == 1
        await old.close()
        assert host._loader.registry.get_startup_hooks() == current_hooks


async def test_sdk_schema_keeps_nested_constraints_in_runtime_wrapper(
    tmp_path,
):
    from qwenpaw.agents import tools
    from qwenpaw.plugins import ToolInputError
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool

    schema = {
        "type": "object",
        "required": ["request"],
        "additionalProperties": False,
        "properties": {
            "request": {
                "type": "object",
                "required": ["quality"],
                "properties": {
                    "quality": {"type": "string", "enum": ["low", "high"]},
                },
            },
        },
    }
    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        ctx.register_tool(
            ToolSpec(
                name="sdk_schema_contract",
                description="Nested schema contract",
                input_schema=SCHEMA,
                handler=lambda call, args: ToolResult.text(
                    args["request"]["quality"]
                ),
                enabled=True,
            )
        )


plugin = Plugin()
""".replace(
        "SCHEMA",
        repr(schema),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        wrapper = GuardedFunctionTool(getattr(tools, "sdk_schema_contract"))
        assert wrapper.input_schema == schema
        with pytest.raises(ToolInputError):
            await host.call_tool(
                "sdk_schema_contract",
                {"request": {"quality": "invalid"}},
            )
        assert (
            await host.call_tool(
                "sdk_schema_contract",
                {"request": {"quality": "high"}},
            )
        ).content[0].text == "high"


async def test_media_preview_uses_real_router_after_host_import(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qwenpaw.app.routers.files import router
    from qwenpaw.plugins.testing import PluginTestHost

    app = FastAPI()
    app.include_router(router, prefix="/api")
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path))
        attachment = ctx.media.write(
            "preview.txt",
            b"readable media",
            mime_type="text/plain",
        )
        with TestClient(app) as client:
            response = client.get(attachment.preview_url)
            assert response.status_code == 200, response.text
            assert response.content == b"readable media"
        assert (await host.reload("author-contract")).ok
        with TestClient(app) as client:
            assert (
                client.get(attachment.preview_url).content == b"readable media"
            )


async def test_legacy_and_sdk_plugins_coexist_without_changing_legacy_dispatch(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
):
    from qwenpaw.agents import tools
    from qwenpaw.plugins import PluginApi
    from qwenpaw.plugins.testing import PluginTestHost

    root = tmp_path / "legacy-peer"
    manifest = write_plugin(
        root,
        """
class Plugin:
    def register(self, api):
        self.api = api
        async def legacy_peer_echo(text: str):
            return api.config["prefix"] + text
        api.register_tool("legacy_peer_echo", legacy_peer_echo, enabled=True)
plugin = Plugin()
""",
        min_version="0.1.0",
        max_version="0.2.0",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        legacy = await host._loader.load_plugin(
            manifest,
            root,
            {"prefix": "legacy:"},
        )
        assert type(legacy.instance.api) is PluginApi
        original = getattr(tools, "legacy_peer_echo")
        assert await original("before") == "legacy:before"
        await host.load(make_plugin(tmp_path))
        assert (
            await host.call_tool("sdk_contract_echo", {"text": "SDK"})
        ).content[0].text == "SDK"
        assert await original("together") == "legacy:together"
        assert (await host.reload("author-contract")).ok
        assert getattr(tools, "legacy_peer_echo") is original
        assert await original("after-sdk-reload") == "legacy:after-sdk-reload"
        assert (await host.unload("author-contract")).quiescent
        assert await original("sdk-removed") == "legacy:sdk-removed"
        assert (await host._loader.lifecycle.reload("legacy-peer")).ok
        assert (
            type(host._loader.get_loaded_plugin("legacy-peer").instance.api)
            is PluginApi
        )
        assert (
            await getattr(tools, "legacy_peer_echo")("reloaded")
            == "legacy:reloaded"
        )


async def test_sdk_prompt_priority_uses_real_default_prompt_assembly(
    tmp_path,
):  # pylint: disable=protected-access
    from pathlib import Path
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.runtime.prompt_contributors import (
        build_default_prompt_manager,
    )
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
from qwenpaw.plugins.prompts import PromptSpec


class Plugin:
    def register(self, ctx):
        ctx.register_prompt(
            PromptSpec(
                "sdk_before", "SDK_BEFORE_WORKSPACE", priority=9
            )
        )
        ctx.register_prompt(
            PromptSpec(
                "sdk_after", "SDK_AFTER_WORKSPACE", priority=11
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        workspace = await host._workspace("test")
        workspace.plugins.prompt_manager = build_default_prompt_manager()
        (Path(workspace.workspace_dir) / "AGENTS.md").write_text(
            "REAL_WORKSPACE_MARKER",
        )
        await host.load(author_plugin(tmp_path, source, ["prompts"]))
        runtime = await host._request_context("test", "chat")
        runtime.extras["language"] = "en"
        prompt = workspace.plugins.prompt_manager.build_sync(runtime)
        assert (
            prompt.index("SDK_BEFORE_WORKSPACE")
            < prompt.index("REAL_WORKSPACE_MARKER")
            < prompt.index("SDK_AFTER_WORKSPACE")
        )
        await host.unload("extension-contract")
        prompt = workspace.plugins.prompt_manager.build_sync(runtime)
        assert "REAL_WORKSPACE_MARKER" in prompt
        assert (
            "SDK_BEFORE_WORKSPACE" not in prompt
            and "SDK_AFTER_WORKSPACE" not in prompt
        )


async def test_sdk_skills_preserve_preexisting_user_owned_same_name(
    tmp_path,
):  # pylint: disable=protected-access
    from pathlib import Path
    from qwenpaw.agents.skill_system.store import get_workspace_skills_dir
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
from qwenpaw.plugins.skills import SkillSpec
class Plugin:
    def register(self, ctx):
        ctx.register_skills(SkillSpec())
plugin = Plugin()
"""
    root = author_plugin(tmp_path, source, ["skills"])
    packaged = root / "skills" / "shared-name" / "SKILL.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(
        "---\nname: shared-name\ndescription: Packaged\n"
        "---\nPackage version.\n",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        workspace = await host._workspace("one")
        user_skill = (
            Path(get_workspace_skills_dir(workspace.workspace_dir))
            / "shared-name"
            / "SKILL.md"
        )
        user_skill.parent.mkdir(parents=True)
        user_content = (
            "---\nname: shared-name\ndescription: User created\n"
            "---\nDo not overwrite.\n"
        )
        user_skill.write_text(user_content)
        await host.load(root)
        assert user_skill.read_text() == user_content
        assert (await host.reload("extension-contract")).ok
        assert user_skill.read_text() == user_content
        await host.unload("extension-contract")
        assert user_skill.read_text() == user_content


async def test_sdk_model_adapter_emits_deltas_and_complete_host_terminal(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
):
    from agentscope.message import Msg, TextBlock
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as author_plugin
    from .test_sdk_provider_contract import SOURCE

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            author_plugin(tmp_path, SOURCE, ["providers", "storage"]),
        )
        public_model = await host.create_model("sdk-provider", "sdk-model")
        stream = await public_model._model(
            [
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(text="question")],
                ),
            ],
        )
        try:
            chunks = [chunk async for chunk in stream]
        finally:
            await stream.aclose()
        deltas = [
            block
            for chunk in chunks
            if not chunk.is_last
            for block in chunk.content
        ]
        assert [block.type for block in deltas] == [
            "thinking",
            "tool_call",
            "text",
        ]
        assert deltas[-1].text == "answer"
        assert [block.model_dump() for block in chunks[-1].content] == [
            block.model_dump() for block in deltas
        ]
        assert chunks[-1].is_last is True
        assert (
            chunks[-1].usage.input_tokens == 12
            and chunks[-1].usage.output_tokens == 3
        )


async def test_sdk_websocket_authenticates_before_scope_creation(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app import auth
    from qwenpaw.config import load_config, save_config
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
from qwenpaw.plugins.apps import PawApp
class Plugin:
    def register(self, plugin):
        app = PawApp(app_id="sdk-auth-app")
        @app.websocket("/identity")
        async def identity(ctx, connection):
            plugin.storage.write_json("ws-principal.json", ctx.user_id)
            await connection.send(ctx.user_id)
            await connection.close()
        plugin.register_app(app)
plugin = Plugin()
"""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    async with PluginTestHost(tmp_path / "host") as host:
        config = load_config()
        config.security.allow_no_auth_hosts = []
        save_config(config)
        token = auth.register_user("alice", "test-only-strong-password")
        assert token and auth.verify_token(token) == "alice"
        host._http_app.add_middleware(auth.AuthMiddleware)
        ctx = await host.load(
            author_plugin(tmp_path, source, ["apps", "storage"]),
        )
        # Do not inject state.user: production HTTP middleware skips WS scopes.
        for headers in ({}, {"Authorization": "Bearer invalid-test-token"}):
            with pytest.raises(SDKError):
                async with host.websocket(
                    "/api/sdk-auth-app/identity",
                    user_id=None,
                    headers=headers,
                ):
                    pytest.fail("Unauthenticated WebSocket was accepted")
            assert ctx.storage.read_json("ws-principal.json", None) is None
        async with host.websocket(
            "/api/sdk-auth-app/identity",
            user_id=None,
            headers={"Authorization": f"Bearer {token}"},
        ) as socket:
            assert await socket.receive() == "alice"
            assert await socket.receive() is None
        assert ctx.storage.read_json("ws-principal.json") == "alice"


@pytest.mark.parametrize("method", ["check_connection", "fetch_models"])
@pytest.mark.parametrize("synchronous", [False, True])
async def test_provider_discovery_deadline_cancels_actual_callback(
    tmp_path,
    method,
    synchronous,
):
    from .sdk_author_fixture import make_plugin as author_plugin
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.providers.provider_manager import ProviderManager

    callback = """
        async def callback(call, timeout):
            now = time.monotonic()
            assert now < call.deadline <= now + timeout
            try:
                await asyncio.sleep(100)
            finally:
                plugin.storage.write_json("callback-stopped.json", True)
"""
    if synchronous:
        callback = """
        def callback(call, timeout):
            now = time.monotonic()
            assert now < call.deadline <= now + timeout
            safety_deadline = time.monotonic() + 2
            try:
                while (
                    not call.cancelled and time.monotonic() < safety_deadline
                ):
                    time.sleep(0.005)
                plugin.storage.write_json(
                    "cancel-observed.json", call.cancelled
                )
                return ConnectionResult(True)
            finally:
                plugin.storage.write_json("callback-stopped.json", True)
"""
    source = """
import asyncio
import time
from qwenpaw.plugins.providers import (
    ProviderSpec, ModelChunk, ConnectionResult,
)
class Plugin:
    def register(self, plugin):
__CALLBACK__
        async def generate(call, request):
            yield ModelChunk((), is_last=True)
        plugin.register_provider(ProviderSpec(
            "deadline-provider", "Deadline", generate, discover=callback,
            check_connection=callback, require_api_key=False,
        ))
plugin = Plugin()
""".replace(
        "__CALLBACK__",
        callback,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            author_plugin(tmp_path, source, ["providers", "storage"]),
        )
        provider = ProviderManager.get_instance().get_provider(
            "deadline-provider",
        )
        with pytest.raises(TimeoutError):
            await getattr(provider, method)(timeout=0.05)
        assert ctx.storage.read_json("callback-stopped.json") is True
        if synchronous:
            assert ctx.storage.read_json("cancel-observed.json") is True
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )
        assert (await host.reload("extension-contract")).ok


async def test_runtime_tool_result_json_history_retains_preview_and_author_metadata(  # noqa: E501
    tmp_path,
):
    from agentscope.message import Msg, ToolResultBlock
    from qwenpaw.agents import tools
    from qwenpaw.plugins._messages import from_host
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.runtime.tool_guard import GuardedFunctionTool
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def image(call, args):
            attachment = call.media.write(
                "history.png", b"image", mime_type="image/png"
            )
            return ToolResult(
                (ContentBlock("image", attachment=attachment),),
                metadata=args,
            )

        ctx.register_tool(
            ToolSpec(
                "history_image",
                "image",
                {"type": "object"},
                image,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    metadata = {
        "_sdk_event": "author",
        "is_error": "author",
        "_sdk_author_metadata": ["author"],
        "_sdk_attachment_previews": {
            "format": "qwenpaw-attachment-previews/1",
            "refs": {},
        },
    }
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(author_plugin(tmp_path, source, ["tools", "storage"]))
        # __new__ returns a callable FunctionTool at runtime.
        # pylint: disable-next=not-callable
        stream = await GuardedFunctionTool(getattr(tools, "history_image"))(
            **metadata,
        )
        try:
            chunks = [chunk async for chunk in stream]
        finally:
            await stream.aclose()
        result = next(chunk for chunk in chunks if chunk.content)
        # AgentScope tool execution uses the same ToolResultBlock fields.
        message = Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolResultBlock(
                    id="call",
                    name="history_image",
                    output=result.content,
                    state="success",
                    metadata=result.metadata,
                ),
            ],
        )
        restored = from_host(
            Msg.model_validate_json(message.model_dump_json()),
        ).content[0]
        assert restored.metadata == metadata
        assert restored.output[0].attachment.preview_url.startswith(
            "/api/files/preview/",
        )


async def test_workspace_delegation_rejects_disabled_target_and_old_generation(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
):
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins import StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_workspace_contract import setup

    async with PluginTestHost(tmp_path / "host") as host:
        await setup(host, tmp_path)
        assert (
            await host.request(
                "GET",
                "/api/workspace-probe/capture/two",
                user_id="alice",
            )
        ).status == 200
        saved = host._loader.get_loaded_plugin(
            "extension-contract",
        ).instance.saved
        config = load_config()
        config.agents.profiles["two"].enabled = False
        save_config(config)
        listing = (
            await host.request("GET", "/api/workspace-probe/workspaces")
        ).json()
        assert (
            next(item for item in listing["items"] if item["id"] == "two")[
                "enabled"
            ]
            is False
        )
        assert (
            await host.request(
                "GET",
                "/api/workspace-probe/capture/two",
                user_id="alice",
            )
        ).status == 403
        config.agents.profiles["two"].enabled = True
        save_config(config)
        assert (await host.reload("extension-contract")).ok
        with pytest.raises(StaleContextError):
            async with saved.for_workspace("two"):
                pytest.fail("Old-generation workspace delegation was accepted")


async def test_cancel_at_tracker_terminal_lock_does_not_leak_async_generator_context(  # noqa: E501  # pylint: disable=protected-access
    tmp_path,
    monkeypatch,
):
    import gc
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_app_contract import app_plugin

    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(
        lambda _loop, context: errors.append(
            str(context.get("exception") or context.get("message")),
        ),
    )
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            context = await host.load(app_plugin(tmp_path))
            tracker = (await host._workspace("test")).task_tracker
            real_lock = tracker._lock
            write = context.storage.write_json
            terminal_persisted = False
            entered, release = asyncio.Event(), asyncio.Event()

            def observe_terminal(key, value, *args, **kwargs):
                nonlocal terminal_persisted
                result = write(key, value, *args, **kwargs)
                if (
                    str(key).startswith("sdk-task-status/")
                    and value.get("status") == "completed"
                ):
                    terminal_persisted = True
                return result

            class TerminalGate:
                async def __aenter__(self):
                    producer = asyncio.current_task().get_coro().__qualname__
                    if (
                        terminal_persisted
                        and producer.endswith(
                            "TaskTracker.attach_or_start.<locals>._producer",
                        )
                        and not entered.is_set()
                    ):
                        entered.set()
                        await release.wait()
                    return await real_lock.__aenter__()

                async def __aexit__(self, *args):
                    return await real_lock.__aexit__(*args)

            monkeypatch.setattr(tracker, "_lock", TerminalGate())
            monkeypatch.setattr(
                context.storage,
                "write_json",
                observe_terminal,
            )
            try:
                started = await host.request(
                    "POST",
                    "/api/sdk-app/tasks",
                    user_id="alice",
                    json={
                        "message": "/appprobe terminal",
                        "session_id": "terminal",
                    },
                )
                assert started.status == 200
                await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
                response = await host.request(
                    "POST",
                    f'/api/sdk-app/tasks/{started.json()["run_id"]}/cancel',
                    user_id="alice",
                )
                assert (
                    response.status == 200
                    and response.json()["stopped"] is True
                )
                await asyncio.sleep(0.05)
                gc.collect()
                await asyncio.sleep(0.05)
                assert not errors
                host.assert_quiescent("extension-contract")
            finally:
                release.set()
                monkeypatch.setattr(tracker, "_lock", real_lock)
                monkeypatch.setattr(context.storage, "write_json", write)
    finally:
        loop.set_exception_handler(previous)


def test_sdk_dependency_uv_reinstall_plan_is_rejected_before_mutation(
    tmp_path,
    monkeypatch,
):
    """Internal installer check; direct URLs remain outside the Gate."""
    import importlib.metadata
    import shutil
    import subprocess
    import sys
    import zipfile
    from qwenpaw.plugins import SDKRestartRequiredError
    from qwenpaw.plugins import _sdk_dependencies as dependencies

    target = tmp_path / "site"
    target.mkdir()
    archive = tmp_path / "sdk_plan_child-1.0-py3-none-any.whl"
    files = {
        "sdk_plan_child/__init__.py": "VALUE = 'old'\n",
        "sdk_plan_child-1.0.dist-info/METADATA": (
            "Metadata-Version: 2.1\nName: sdk-plan-child\nVersion: 1.0\n"
        ),
        "sdk_plan_child-1.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    files["sdk_plan_child-1.0.dist-info/RECORD"] = "".join(
        f"{key},,\n" for key in files
    )
    for key, value in files.items():
        destination = target / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(value)
    files["sdk_plan_child/__init__.py"] = "VALUE = 'replacement'\n"
    with zipfile.ZipFile(archive, "w") as output:
        for key, value in files.items():
            output.writestr(key, value)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sdk-plan-child @ " + archive.as_uri() + "\n")
    monkeypatch.setattr(
        dependencies,
        "distributions",
        lambda: importlib.metadata.distributions(path=[str(target)]),
    )
    for key in ("UV_CACHE_DIR", "UV_CREDENTIALS_DIR", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    monkeypatch.setenv("UV_NO_INDEX", "1")
    uv = shutil.which("uv")
    assert (
        uv
    ), "The isolated test environment must provide its dependency resolver"
    commands = []

    def run(args, **_):
        assert (
            "--dry-run" in args
        ), "A reinstall plan reached a mutating command"
        commands.append(args)
        if "--report" in args:
            # Select the actual uv fallback without relying on whether this
            # pytest interpreter happens to have pip installed.
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "No module named pip",
            )
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        (tmp_path / "uv-plan.txt").write_text(result.stdout + result.stderr)
        return result

    with pytest.raises(SDKRestartRequiredError):
        dependencies.install_sdk_requirements(
            requirements,
            "plan-contract",
            python=sys.executable,
            target=str(target),
            run=run,
            find_uv=lambda: uv,
        )
    assert len(commands) == 2
    assert (
        target / "sdk_plan_child/__init__.py"
    ).read_text() == "VALUE = 'old'\n"
    assert (
        "Would uninstall 1 package" in (tmp_path / "uv-plan.txt").read_text()
    )


@pytest.mark.parametrize("resolver", ["pip", "uv"])
def test_sdk_dependency_unknown_plan_never_reaches_mutating_install(
    tmp_path,
    monkeypatch,
    resolver,
):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from qwenpaw.plugins import SDKRestartRequiredError
    from qwenpaw.plugins import _sdk_dependencies as dependencies

    monkeypatch.setattr(dependencies, "distributions", lambda: ())
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("unknown-plan-package==1\n")
    commands = []

    def run(args, **_):
        assert "--dry-run" in args
        commands.append(args)
        if "--report" in args:
            if resolver == "uv":
                return subprocess.CompletedProcess(
                    args,
                    1,
                    "",
                    "No module named pip",
                )
            Path(args[args.index("--report") + 1]).write_text(
                json.dumps({"version": "future-format", "install": []}),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            "Future resolver plans do not use the known schema",
            "",
        )

    with pytest.raises(SDKRestartRequiredError):
        dependencies.install_sdk_requirements(
            requirements,
            "plan-contract",
            python=sys.executable,
            target=None,
            run=run,
            find_uv=lambda: "uv",
        )
    assert len(commands) == (2 if resolver == "uv" else 1)


@pytest.mark.parametrize("early_error", [False, True])
async def test_call_tool_matches_production_stream_aggregation(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
    early_error,
):
    from agentscope.tool import ToolResponse
    from qwenpaw.agents import tools
    from qwenpaw.plugins._messages import _from_block, _take_tool_metadata
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.governance.tool_adapter import PolicyGuardedTool
    from agentscope.permission import PermissionBehavior

    source = f"""
from qwenpaw.plugins.messages import Attachment, ContentBlock
from qwenpaw.plugins.tools import ToolEvent, ToolResult, ToolSpec
class Plugin:
    def register(self, ctx):
        async def stream(call, arguments):
            yield ToolEvent("delta", (ContentBlock(text="prefix:"),))
            yield ToolEvent("result", result=ToolResult(
                (ContentBlock(text="first"),), is_error={early_error!r},
                metadata={{"first": 1, "collision": "old"}},
            ))
            yield ToolEvent("result", result=ToolResult(
                (ContentBlock(type="file", attachment=Attachment(
                    url="https://example.invalid/result.txt",
                    name="result.txt",
                    preview_url="/api/files/preview?path=result.txt")),
                 ContentBlock(text="last")),
                metadata={{"last": 2, "collision": "new"}},
            ))
        ctx.register_tool(ToolSpec(
            "sdk_aggregate_probe", "stream", {{"type": "object"}},
            stream, enabled=True,
        ))
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        result = await host.call_tool("sdk_aggregate_probe", {})
        tool = PolicyGuardedTool(
            getattr(tools, "sdk_aggregate_probe"),
            governor=host._governors["test"],
            request_context={"agent_id": "test", "session_id": "test"},
        )
        assert (
            await tool.check_permissions({})
        ).behavior is PermissionBehavior.ALLOW
        response = ToolResponse()
        # PolicyGuardedTool.__new__ returns a callable FunctionTool.
        # pylint: disable-next=not-callable
        stream = await tool()
        terminals = 0
        async for chunk in stream:
            terminals += int(chunk.is_last)
            response.append_chunk(chunk)
        metadata, previews, kind, error, block_metadata = _take_tool_metadata(
            response.metadata,
            response.content,
        )
        production = tuple(
            _from_block(block, previews, block_metadata, str(index))
            for index, block in enumerate(response.content)
        )
        assert terminals == 1 and kind == "end"
        assert [block.type for block in production] == ["text", "file", "text"]
        assert [
            block.text for block in production if block.type == "text"
        ] == [
            "prefix:first",
            "last",
        ]
        assert error is early_error
        assert metadata == {"first": 1, "last": 2, "collision": "new"}
        # Compare public values rather than generated host block IDs.
        describe = lambda content: [
            (b.type, b.text, b.attachment, b.metadata) for b in content
        ]
        assert (
            describe(result.content),
            result.is_error,
            result.metadata,
        ) == (
            describe(production),
            error,
            metadata,
        )


async def test_official_async_template_keeps_loop_responsive(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
    monkeypatch,
):
    import shutil
    import threading
    import time
    from pathlib import Path
    import qwenpaw.plugins
    from qwenpaw.plugins.testing import PluginTestHost

    TEMPLATE = Path(qwenpaw.plugins.__file__).parent / "templates" / "hello"
    package = tmp_path / "hello"
    shutil.copytree(TEMPLATE, package)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(package)
        await host.call_tool("hello_sdk", {"name": "warm"})
        ticks = []
        observations = []
        original = os.fsync

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.005)

        heart = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.01)

        def slow_fsync(fd):
            before = len(ticks)
            wait_for_thread_progress(lambda: len(ticks) > before)
            observations.append(
                (threading.current_thread().name, len(ticks) - before),
            )
            return original(fd)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "fsync", slow_fsync)
                result = await host.call_tool("hello_sdk", {"name": "slow"})
            assert "Hello slow (2)" in "".join(b.text for b in result.content)
            assert observations and all(
                delta > 0 for _, delta in observations
            ), observations
        finally:
            heart.cancel()
            await asyncio.gather(heart, return_exceptions=True)


@pytest.mark.parametrize(
    "owner",
    ["root-storage", "tool-storage", "root-media"],
)
@pytest.mark.usefixtures("short_interrupt_timeout")
async def test_async_file_transaction_retains_owner_until_real_io_finishes(  # pylint: disable=too-many-statements  # noqa: E501
    tmp_path,
    monkeypatch,
    owner,
):
    import threading
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
from qwenpaw.plugins.tools import ToolResult, ToolSpec


class Plugin:
    def register(self, ctx):
        async def persist(call, args):
            await call.storage.awrite_json(
                "state.json", {"version": 1}
            )
            return ToolResult.text("written")

        async def read(call, args):
            return ToolResult.text(
                str(await call.storage.aread_json("state.json"))
            )

        ctx.register_tool(
            ToolSpec(
                "async_persist",
                "persist",
                {"type": "object"},
                persist,
                enabled=True,
            )
        )
        ctx.register_tool(
            ToolSpec(
                "async_read",
                "read",
                {"type": "object"},
                read,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    entered, release, finished = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    import tempfile
    from pathlib import Path

    original = os.fsync
    original_mkstemp = tempfile.mkstemp
    storage_fds = set()
    observations = []

    def storage_temporary(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        if "plugin-data" in Path(name).parts or "plugins" in Path(name).parts:
            storage_fds.add(fd)
        return fd, name

    def controlled_fsync(fd):
        if fd not in storage_fds:
            return original(fd)
        storage_fds.remove(fd)
        observations.append(threading.current_thread().name)
        entered.set()
        assert release.wait(
            WAIT_TIMEOUT * 2,
        ), "Test did not release the actual filesystem operation"
        result = original(fd)
        finished.set()
        return result

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            author_plugin(tmp_path, source, ["tools", "storage"]),
        )
        task = None
        try:
            with monkeypatch.context() as patch:
                patch.setattr(tempfile, "mkstemp", storage_temporary)
                patch.setattr(os, "fsync", controlled_fsync)
                if owner == "tool-storage":
                    operation = host.call_tool("async_persist", {})
                elif owner == "root-media":
                    operation = ctx.media.awrite("state.txt", b"version-one")
                else:
                    operation = ctx.storage.awrite_json(
                        "state.json",
                        {"version": 1},
                    )
                task = asyncio.create_task(operation)
                async with asyncio.timeout(WAIT_TIMEOUT):
                    while not entered.is_set():
                        await asyncio.sleep(0.005)
                task.cancel()
                await asyncio.sleep(0.02)
                task.cancel()
                assert not task.done() and not finished.is_set()
                with pytest.raises(PluginBusyError):
                    await host.reload(
                        "extension-contract",
                        interrupt_tasks=True,
                    )
                assert not finished.is_set()
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
                if owner != "tool-storage":
                    assert not task.done()
                release.set()
                assert await asyncio.to_thread(finished.wait, WAIT_TIMEOUT)
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert finished.is_set() and observations
            assert all(name != "MainThread" for name in observations)
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
            current = host.context("extension-contract")
            if owner == "tool-storage":
                result = await host.call_tool("async_read", {})
                assert "'version': 1" in "".join(
                    block.text for block in result.content
                )
            elif owner == "root-storage":
                assert await current.storage.aread_json("state.json") == {
                    "version": 1,
                }
                await current.storage.awrite_json("state.json", {"version": 2})
                assert current.storage.read_json("state.json") == {
                    "version": 2,
                }
            else:
                attachment = await current.media.awrite(
                    "state.txt",
                    b"version-two",
                )
                from qwenpaw.utils.media_paths import file_url_to_path

                assert (
                    Path(file_url_to_path(attachment.url)).read_bytes()
                    == b"version-two"
                )
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)


async def test_readonly_plugin_ignores_stale_entry_and_child_bytecode(
    tmp_path,
):
    import hashlib
    import py_compile
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as author_plugin

    source = """
import helper
from qwenpaw.plugins.tools import ToolResult, ToolSpec

VALUE = "one"


class Plugin:
    def register(self, ctx):
        async def value(call, args):
            return ToolResult.text(VALUE + ":" + helper.VALUE)

        ctx.register_tool(
            ToolSpec(
                "cached_value",
                "value",
                {"type": "object"},
                value,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    package = author_plugin(tmp_path, source, ["tools"])
    child = package / "helper.py"
    child.write_text("VALUE = 'one'\n")
    sources = [package / "main.py", child]
    mtimes = {p: p.stat().st_mtime_ns for p in sources}
    for path in sources:
        py_compile.compile(str(path), doraise=True)
        content = path.read_text()
        assert content.count("one") == 1
        updated = content.replace("one", "two")
        assert len(updated.encode()) == len(content.encode())
        path.write_text(updated)
        os.utime(path, ns=(mtimes[path], mtimes[path]))
    cached = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in package.rglob("*.pyc")
    }
    assert len(cached) == 2
    files = [p for p in package.rglob("*") if p.is_file()]
    directories = [p for p in package.rglob("*") if p.is_dir()]
    for path in files:
        path.chmod(0o444)
    for path in directories:
        path.chmod(0o555)
    package.chmod(0o555)
    try:
        if os.access(package / "__pycache__", os.W_OK):
            pytest.skip(
                "This process cannot enforce a read-only cache directory",
            )
        async with PluginTestHost(tmp_path / "host") as host:
            await host.load(package)
            result = await host.call_tool("cached_value", {})
            assert "".join(p.text for p in result.content) == "two:two"
            for path in sources:
                path.chmod(0o644)
                before = path.stat()
                content = path.read_text()
                assert content.count("two") == 1
                updated = content.replace("two", "tri")
                assert len(updated.encode()) == len(content.encode())
                path.write_text(updated)
                os.utime(path, ns=(before.st_atime_ns, mtimes[path]))
                assert path.stat().st_size == before.st_size
                path.chmod(0o444)
            assert (await host.reload("extension-contract")).ok
            result = await host.call_tool("cached_value", {})
            assert "".join(p.text for p in result.content) == "tri:tri"
            assert {
                p: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in package.rglob("*.pyc")
            } == cached
    finally:
        package.chmod(0o755)
        for path in directories:
            path.chmod(0o755)
        for path in files:
            path.chmod(0o644)


@pytest.mark.parametrize("path_style", ["windows", "windows-forward", "posix"])
@pytest.mark.parametrize("operation", ["private-import", "private-call"])
async def test_runtime_checker_profiles_native_style_paths(  # pylint: disable=protected-access  # noqa: E501
    tmp_path,
    monkeypatch,
    path_style,
    operation,
):
    from pathlib import PureWindowsPath
    from qwenpaw.plugins import check, testing
    from qwenpaw.plugins.compliance import check_plugin
    from .sdk_author_fixture import make_plugin as author_plugin

    class WindowsPath(PureWindowsPath):
        def resolve(self):
            return self

    package = author_plugin(
        tmp_path,
        "class Plugin:\n    def register(self, ctx): pass\nplugin=Plugin()\n",
        [],
    )
    directory = (
        WindowsPath(r"C:\plugins\demo")
        if path_style.startswith("windows")
        else package
    )
    filename = str(directory / "main.py")
    if path_style == "windows-forward":
        filename = filename.replace("\\", "/")
    source = (
        "import importlib\nimportlib.import_module('qwenpaw.plugins.loader')\n"
    )
    if operation == "private-call":
        source = """
from qwenpaw.runtime.hooks import HookContext

hook = HookContext(
    request=None,
    session_id="test",
    agent_id="test",
    root_session_id="test",
    root_agent_id="test",
    workspace_dir=None,
    workspace=None,
    app_services=None,
)
hook.inject_context("probe")
"""

    class RuntimeHost:
        def __init__(self, root):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def load(self, target):
            assert target == directory
            exec(compile(source, filename, "exec"), {})

    actual_path = check.Path
    monkeypatch.setattr(
        check,
        "Path",
        lambda value: (
            WindowsPath(value)
            if str(value).startswith("C:")
            else actual_path(value)
        ),
    )
    monkeypatch.setattr(testing, "PluginTestHost", RuntimeHost)
    report = await check._runtime(directory, check_plugin(package))
    expected = "runtime-" + operation
    assert any(
        row.code == expected for row in report.findings
    ), report.findings
    assert not any(row.code == "runtime-failure" for row in report.findings)


@pytest.mark.parametrize("compiled", [False, True])
def test_plugin_probe_discovers_new_module_after_cached_miss(
    tmp_path,
    compiled,
):
    import importlib
    from qwenpaw.plugins.module_isolation import probe_plugin_source

    entry = tmp_path / "main.py"
    entry.write_text("from .newhelper import VALUE\nplugin = VALUE\n")
    assert (
        importlib.machinery.PathFinder.find_spec("newhelper", [str(tmp_path)])
        is None
    )
    before = tmp_path.stat()
    (tmp_path / "newhelper.py").write_text("VALUE = object()\n")
    os.utime(tmp_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    try:
        probe_plugin_source(
            "new-module-probe",
            tmp_path,
            entry,
            compiled=compiled,
        )
    finally:
        importlib.invalidate_caches()


async def test_app_repeated_cancel_finishes_provider_cleanup(
    tmp_path,
    monkeypatch,
):
    import sys
    from types import SimpleNamespace

    from qwenpaw.plugins.resources import ResourceScope
    from qwenpaw.plugins.testing import PluginTestHost
    from .sdk_author_fixture import make_plugin as make_extension

    probe = SimpleNamespace(
        ready=asyncio.Event(),
        finish=asyncio.Event(),
        scope=None,
    )
    entered, release = (asyncio.Event() for _ in range(2))
    close = ResourceScope.close

    async def delayed_close(scope):
        if scope is probe.scope and not scope.closed:
            entered.set()
            await release.wait()
        await close(scope)

    monkeypatch.setattr(ResourceScope, "close", delayed_close)
    monkeypatch.setitem(sys.modules, "sdk_close_probe", probe)
    source = """
import asyncio
import sdk_close_probe as probe
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk

class Plugin:
    def register(self, plugin):
        async def generate(ctx, request):
            probe.scope = ctx.resources
            yield ModelChunk((ContentBlock(text="started"),))
            probe.ready.set()
            while not probe.finish.is_set():
                try:
                    await probe.finish.wait()
                except asyncio.CancelledError:
                    pass
            yield ModelChunk((ContentBlock(text="finished"),), is_last=True)

        plugin.register_provider(ProviderSpec(
            "cleanup-probe", "Cleanup probe", generate,
            models=(ModelInfo("probe", "Probe"),), require_api_key=False,
        ))
        app = PawApp(app_id="cleanup-probe").enable_standard_capabilities()

        @app.route("/stop/{id}", methods=("POST",))
        async def stop(ctx, request):
            result = await ctx.cancel_task(
                request.path_params["id"], timeout=0.05
            )
            return {"stopped": result.stopped}

        plugin.register_app(app)

plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_extension(tmp_path, source, ["apps", "providers"]),
        )
        await host.configure_chat_model("cleanup-probe", "probe")
        started = await host.request(
            "POST",
            "/api/cleanup-probe/tasks",
            json={"message": "start"},
        )
        assert started.status == 200
        run_id = started.json()["run_id"]
        stop = "/api/cleanup-probe/stop/" + run_id
        status = "/api/cleanup-probe/tasks/" + run_id
        try:
            await asyncio.wait_for(probe.ready.wait(), WAIT_TIMEOUT)
            assert not (await host.request("POST", stop)).json()["stopped"]
            probe.finish.set()
            await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
            assert not (await host.request("POST", stop)).json()["stopped"]
            release.set()
            # No further stop request may be needed once cleanup can finish.
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (await host.request("GET", status)).json()[
                    "status"
                ] == "running":
                    await asyncio.sleep(0.01)
                while host.resource_snapshot("extension-contract")[
                    "active_calls"
                ]:
                    await asyncio.sleep(0.01)
            assert (await host.request("GET", status)).json()[
                "status"
            ] == "cancelled"
            assert probe.scope.closed
        finally:
            probe.finish.set()
            release.set()
            if host.resource_snapshot("extension-contract")["active_calls"]:
                await host.request("POST", stop)
