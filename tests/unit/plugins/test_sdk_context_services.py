# -*- coding: utf-8 -*-
"""Portable author checks of bound logging and real configured model calls."""

import json
import logging

import pytest


def package(root, plugin_id, source, capabilities):
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": capabilities},
            },
        ),
    )
    (root / "main.py").write_text(source)
    return root


PROVIDER = """
from dataclasses import asdict
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
            key = call.workspace_id + "-" + call.session_id
            ctx.storage.write_json(
                key + ".json",
                {
                    "workspace": call.workspace_id,
                    "session": call.session_id,
                    "model": request.model_id,
                    "messages": [
                        asdict(message)
                        for message in request.messages
                    ],
                    "tools": list(request.tools),
                    "options": request.options,
                    "choice": (
                        asdict(request.tool_choice)
                        if request.tool_choice
                        else None
                    ),
                },
            )
            try:
                yield ModelChunk(
                    (ContentBlock(text="first:"),), id="bound-model"
                )
                yield ModelChunk(
                    (ContentBlock(type="thinking", text="reason"),),
                    id="bound-model",
                )
                yield ModelChunk(
                    (
                        ContentBlock(
                            type="tool_call",
                            id="calculation",
                            name="calculate",
                            arguments='{"x":3}',
                        ),
                    ),
                    id="bound-model",
                )
                yield ModelChunk(
                    (ContentBlock(text="last"),),
                    is_last=True,
                    usage=ModelUsage(
                        12, 3, metadata={"meter": "kept"}
                    ),
                    id="bound-model",
                    metadata={"finish": "kept"},
                )
            finally:
                ctx.storage.write_json(key + "-closed.json", True)

        ctx.register_provider(
            ProviderSpec(
                "context-provider",
                "Context provider",
                generate,
                models=(
                    ModelInfo("default-model", "Default"),
                    ModelInfo("explicit-model", "Explicit"),
                ),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""

CALLER = """
from dataclasses import asdict
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.providers import ModelToolChoice
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
from qwenpaw.plugins.apps import PawApp


async def invoke(call, args):
    messages = (
        Message(
            "user",
            (ContentBlock(text="question"),),
            metadata={"source": "author"},
        ),
    )
    kwargs = dict(
        options={"temperature": 0.2},
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "calculate",
                    "parameters": {"type": "object"},
                },
            },
        ),
        tool_choice=ModelToolChoice("auto"),
    )
    if args.get("explicit"):
        kwargs.update(
            provider_id="context-provider",
            model_id="explicit-model",
        )
    if args.get("stream"):
        stream = call.models.stream(messages, **kwargs)
        try:
            chunks = [chunk async for chunk in stream]
        finally:
            await stream.aclose()
        return {"chunks": [asdict(chunk) for chunk in chunks]}
    return {
        "result": asdict(
            await call.models.complete(messages, **kwargs)
        )
    }


class Plugin:
    def register(self, ctx):
        async def tool(call, args):
            return ToolResult(metadata=await invoke(call, args))

        async def command(call, args):
            result = await invoke(call, {})
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="command"),),
                    metadata=result,
                ),
            )

        async def hook(call):
            result = await invoke(call, {})
            return HookResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="hook"),),
                    metadata=result,
                ),
            )

        app = PawApp("Context app", app_id="context-app")

        @app.route("/invoke", methods=["POST"])
        async def route(call, request):
            return await invoke(call, request.json())

        ctx.register_app(app)
        ctx.register_tool(
            ToolSpec(
                "context_model_tool",
                "Call the configured model",
                {
                    "type": "object",
                    "properties": {
                        "explicit": {"type": "boolean"},
                        "stream": {"type": "boolean"},
                    },
                },
                tool,
                enabled=True,
            )
        )
        ctx.register_command(CommandSpec("contextmodel", command))
        ctx.register_hook(
            HookSpec(
                "context-model-hook", HookPhase.PRE_DISPATCH, hook
            )
        )


plugin = Plugin()
"""


async def load_services(host, tmp_path):
    provider = await host.load(
        package(
            tmp_path / "provider",
            "context-provider-plugin",
            PROVIDER,
            ["providers", "storage"],
        ),
    )
    caller = await host.load(
        package(
            tmp_path / "caller",
            "context-caller-plugin",
            CALLER,
            ["tools", "commands", "hooks", "apps"],
        ),
    )
    for workspace in ("one", "two"):
        await host.configure_chat_model(
            "context-provider",
            "default-model",
            workspace_id=workspace,
        )
    return provider, caller


def assert_complete(value):
    assert value["is_last"] is True
    assert value["id"] == "bound-model"
    assert value["finished_reason"] == "completed"
    assert [block["type"] for block in value["content"]] == [
        "text",
        "thinking",
        "tool_call",
        "text",
    ]
    assert [block["text"] for block in value["content"]] == [
        "first:",
        "reason",
        "",
        "last",
    ]
    assert value["content"][2]["arguments"] == '{"x":3}'
    assert value["usage"]["input_tokens"] == 12
    assert value["usage"]["output_tokens"] == 3
    assert value["usage"]["metadata"] == {"meter": "kept"}
    assert value["metadata"] == {"finish": "kept"}


@pytest.mark.parametrize("entry", ["tool", "command", "hook", "app"])
async def test_bound_context_calls_real_configured_model(tmp_path, entry):
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.plugins.hooks import HookPhase

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_services(host, tmp_path)
        if entry == "tool":
            value = (
                await host.call_tool(
                    "context_model_tool",
                    {},
                    workspace_id="one",
                    session_id="conversation",
                )
            ).metadata
        elif entry == "command":
            value = (
                await host.call_command(
                    "/contextmodel",
                    workspace_id="one",
                    session_id="conversation",
                )
            ).metadata
        elif entry == "hook":
            value = (
                await host.run_hooks(
                    HookPhase.PRE_DISPATCH,
                    workspace_id="one",
                    session_id="conversation",
                )
            ).message.metadata
        else:
            response = await host.request(
                "POST",
                "/api/context-app/invoke",
                workspace_id="one",
                json={},
            )
            assert response.status == 200, response.text
            value = response.json()
        assert_complete(value["result"])
        # The provider, rather than a fake ModelService, must have observed
        # this call.
        if entry != "app":
            request = provider.storage.read_json("one-conversation.json")
            assert (
                request["workspace"] == "one"
                and request["session"] == "conversation"
            )
            assert request["model"] == "default-model"
            assert request["messages"][0]["content"][0]["text"] == "question"
            assert request["messages"][0]["metadata"] == {"source": "author"}
            assert request["options"] == {"temperature": 0.2}
            assert request["choice"] == {"mode": "auto", "tools": None}
            assert request["tools"][0]["function"]["name"] == "calculate"
            assert (
                provider.storage.read_json("one-conversation-closed.json")
                is True
            )


@pytest.mark.parametrize("streaming", [False, True])
async def test_bound_models_explicit_selection_and_stream_terminal_once(
    tmp_path,
    streaming,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_services(host, tmp_path)
        result = await host.call_tool(
            "context_model_tool",
            {"explicit": True, "stream": streaming},
            workspace_id="two",
            session_id="separate",
        )
        if streaming:
            chunks = result.metadata["chunks"]
            assert [chunk["is_last"] for chunk in chunks] == [False] * (
                len(chunks) - 1
            ) + [True]
            assert [
                block["text"] for chunk in chunks for block in chunk["content"]
            ] == ["first:", "reason", "", "last"]
            assert chunks[-1]["usage"]["input_tokens"] == 12
            assert chunks[-1]["metadata"] == {"finish": "kept"}
        else:
            assert_complete(result.metadata["result"])
        request = provider.storage.read_json("two-separate.json")
        assert request["model"] == "explicit-model"
        assert (
            request["workspace"] == "two" and request["session"] == "separate"
        )


async def test_logger_binds_identity_without_accepting_author_field_spoofing(
    tmp_path,
    caplog,
):
    from qwenpaw.plugins import StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        def log(call, args):
            call.logger.info(
                "bound-author-log",
                fields={
                    "plugin_id": "forged",
                    "workspace_id": "forged",
                    "session_id": "forged",
                    "business": "kept",
                },
            )
            return ToolResult.text("logged")

        ctx.register_tool(
            ToolSpec(
                "context_log_tool",
                "Log",
                {"type": "object"},
                log,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="qwenpaw")
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            package(tmp_path / "logger", "context-logger", source, ["tools"]),
        )
        for workspace, session in (("one", "first"), ("two", "second")):
            await host.call_tool(
                "context_log_tool",
                {},
                workspace_id=workspace,
                session_id=session,
            )
        records = [
            record
            for record in caplog.records
            if record.getMessage() == "bound-author-log"
        ]
        assert len(records) == 2
        for record, (workspace, session) in zip(
            records,
            (("one", "first"), ("two", "second")),
        ):
            assert record.sdk_context["plugin_id"] == "context-logger"
            assert record.sdk_context["generation"] == ctx.generation
            assert record.sdk_context["workspace_id"] == workspace
            assert record.sdk_context["session_id"] == session
            assert record.sdk_fields == {
                "plugin_id": "forged",
                "workspace_id": "forged",
                "session_id": "forged",
                "business": "kept",
            }
        old = ctx.logger
        assert (await host.reload("context-logger")).ok
        with pytest.raises(StaleContextError):
            old.info("stale-must-not-log")
        assert not any(
            record.getMessage() == "stale-must-not-log"
            for record in caplog.records
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"provider_id": "context-provider"},
        {"model_id": "default-model"},
        {"provider_id": "missing", "model_id": "missing"},
        {"options": {"messages": []}},
        {"options": {"api_key": "must-not-override"}},
        {"options": {"unknown_generation_option": True}},
        {"timeout": 0},
    ],
)
async def test_model_service_rejects_invalid_selection_and_reserved_options(
    tmp_path,
    arguments,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="input"),)),),
                **args
            )
            return ToolResult(result.content)

        ctx.register_tool(
            ToolSpec(
                "invalid_bound_model",
                "validate",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "context-provider-plugin",
                PROVIDER,
                ["providers", "storage"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "model-validation",
                source,
                ["tools"],
            ),
        )
        await host.configure_chat_model(
            "context-provider",
            "default-model",
            workspace_id="one",
        )
        with pytest.raises(SDKError):
            await host.call_tool(
                "invalid_bound_model",
                arguments,
                workspace_id="one",
                session_id="rejected",
            )
        assert provider.storage.read_json("one-rejected.json", None) is None


async def test_unconfigured_workspace_does_not_use_another_model(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_services(host, tmp_path)
        with pytest.raises(SDKError):
            await host.call_tool(
                "context_model_tool",
                {},
                workspace_id="unconfigured",
                session_id="none",
            )
        assert (
            provider.storage.read_json("unconfigured-none.json", None) is None
        )


async def test_channel_context_uses_configured_model_and_fixed_log_identity(
    tmp_path,
    caplog,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from dataclasses import asdict
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, ctx):
        class Backend:
            async def start(self, call):
                pass

            async def stop(self, call):
                return True

            async def send(self, call, message):
                call.logger.warning(
                    "channel-model-context",
                    fields={"channel_name": "forged"},
                )
                result = await call.models.complete(
                    (
                        Message(
                            "user",
                            (
                                ContentBlock(
                                    text="channel question"
                                ),
                            ),
                        ),
                    )
                )
                ctx.storage.write_json(
                    "result.json", asdict(result)
                )

        ctx.register_channel(
            ChannelSpec(
                "context_channel", "Context channel", Backend
            )
        )


plugin = Plugin()
"""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="qwenpaw")
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "context-provider-plugin",
                PROVIDER,
                ["providers", "storage"],
            ),
        )
        caller = await host.load(
            package(
                tmp_path / "channel",
                "context-channel-owner",
                source,
                ["channels", "logging", "models", "storage"],
            ),
        )
        await host.configure_chat_model(
            "context-provider",
            "default-model",
            workspace_id="channel-workspace",
        )
        await host.start_channel(
            "context_channel",
            workspace_id="channel-workspace",
        )
        await host.send_channel(
            "context_channel",
            "trigger",
            user_id="channel-user",
            session_id="channel-session",
            workspace_id="channel-workspace",
        )
        assert_complete(caller.storage.read_json("result.json"))
        request = provider.storage.read_json(
            "channel-workspace-channel-session.json",
        )
        assert request["workspace"] == "channel-workspace"
        assert request["session"] == "channel-session"
        record = next(
            r
            for r in caplog.records
            if r.getMessage() == "channel-model-context"
        )
        assert record.sdk_context["channel_name"] == "context_channel"
        assert record.sdk_context["workspace_id"] == "channel-workspace"
        assert record.sdk_context["session_id"] == "channel-session"
        assert record.sdk_fields == {"channel_name": "forged"}
        await host.stop_channel(
            "context_channel",
            workspace_id="channel-workspace",
        )


@pytest.mark.parametrize("streaming", [False, True])
async def test_bound_model_preserves_block_metadata_and_attachment_preview(
    tmp_path,
    streaming,
):
    from qwenpaw.plugins.testing import PluginTestHost

    provider_source = """
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock, Attachment


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            yield ModelChunk(
                (
                    ContentBlock(
                        text="delta",
                        metadata={"author": "text-kept"},
                    ),
                )
            )
            yield ModelChunk(
                (
                    ContentBlock(
                        type="image",
                        attachment=Attachment(
                            url="https://example.invalid/synthetic.png",
                            mime_type="image/png",
                            preview_url="/api/files/preview/synthetic",
                        ),
                        metadata={"author": "image-kept"},
                    ),
                )
            )
            yield ModelChunk((), is_last=True)

        ctx.register_provider(
            ProviderSpec(
                "context-provider",
                "Model metadata",
                generate,
                models=(ModelInfo("default-model", "Default"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            package(
                tmp_path / "provider",
                "context-provider-plugin",
                provider_source,
                ["providers"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "context-caller-plugin",
                CALLER,
                ["tools", "commands", "hooks", "apps", "models"],
            ),
        )
        await host.configure_chat_model(
            "context-provider",
            "default-model",
            workspace_id="one",
        )
        result = await host.call_tool(
            "context_model_tool",
            {"stream": streaming},
            workspace_id="one",
        )
        value = result.metadata
        blocks = (
            [block for chunk in value["chunks"] for block in chunk["content"]]
            if streaming
            else value["result"]["content"]
        )
        assert [block["type"] for block in blocks] == ["text", "image"]
        assert blocks[0]["metadata"] == {"author": "text-kept"}
        assert blocks[1]["metadata"] == {"author": "image-kept"}
        assert (
            blocks[1]["attachment"]["preview_url"]
            == "/api/files/preview/synthetic"
        )


async def test_complete_preserves_nondefault_terminal_reason_and_identity(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = PROVIDER.replace(
        'id="bound-model",\n                    metadata={"finish": "kept"}',
        (
            'id="bound-model", finished_reason="interrupted", '
            'metadata={"finish": "kept"}'
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            package(
                tmp_path / "provider",
                "context-provider-plugin",
                source,
                ["providers", "storage"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "context-caller-plugin",
                CALLER,
                ["tools", "commands", "hooks", "apps", "models"],
            ),
        )
        await host.configure_chat_model(
            "context-provider",
            "default-model",
            workspace_id="one",
        )
        result = await host.call_tool(
            "context_model_tool",
            {},
            workspace_id="one",
        )
        assert result.metadata["result"]["finished_reason"] == "interrupted"
        assert result.metadata["result"]["id"] == "bound-model"
        assert result.metadata["result"]["metadata"] == {"finish": "kept"}


async def test_app_logger_identity_and_cleanup_without_request(
    tmp_path,
    caplog,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.apps import PawApp


class Plugin:
    def register(self, ctx):
        app = PawApp("Logging app", app_id="logging-app")

        @app.route("/log", methods=["POST"])
        async def route(call, request):
            call.logger.warning(
                "app-context-record", fields={"user_id": "forged"}
            )
            call.resources.defer(
                lambda: call.logger.warning("app-cleanup-record")
            )
            return {"ok": True}

        ctx.register_app(app)


plugin = Plugin()
"""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="qwenpaw")
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            package(
                tmp_path / "caller",
                "app-log-owner",
                source,
                ["apps", "logging"],
            ),
        )
        ctx.logger.warning("root-context-record")
        response = await host.request(
            "POST",
            "/api/logging-app/log",
            workspace_id="app-workspace",
            user_id="alice",
        )
        assert response.status == 200
        root = next(
            r
            for r in caplog.records
            if r.getMessage() == "root-context-record"
        )
        assert root.sdk_context == {
            "plugin_id": "app-log-owner",
            "generation": ctx.generation,
        }
        records = [
            r
            for r in caplog.records
            if r.getMessage() in ("app-context-record", "app-cleanup-record")
        ]
        assert len(records) == 2
        assert records[0].sdk_context == records[1].sdk_context
        identity = records[0].sdk_context
        assert identity["app_id"] == "logging-app"
        assert identity["workspace_id"] == "app-workspace"
        assert identity["user_id"] == "alice"
        assert identity["invocation_id"]
        assert "request_id" not in identity and "run_id" not in identity
        assert records[0].sdk_fields == {"user_id": "forged"}


async def test_workspace_directories_keep_identity_storage_config_and_models(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import json
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            count = call.storage.read_json("count.json", 0)
            call.storage.write_json("count.json", count + 1)
            call.logger.info(
                "workspace ownership", fields={"count": count}
            )
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="question"),)),)
            )
            return ToolResult.text(
                json.dumps(
                    {
                        "workspace": call.workspace_id,
                        "count": count,
                        "setting": call.config.get("marker"),
                        "text": "".join(
                            b.text
                            for b in result.content
                            if b.type == "text"
                        ),
                    }
                )
            )

        ctx.register_tool(
            ToolSpec(
                "author_workspace_probe",
                "workspace identity",
                {"type": "object"},
                invoke,
                enabled=True,
                config_fields=({"name": "marker", "type": "text"},),
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(
        tmp_path / "host",
        workspace_dirs={"sales": "sales/shared", "support": "support/shared"},
    ) as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "identity-provider",
                PROVIDER,
                ["providers", "storage"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "identity-caller",
                source,
                ["tools", "models", "logging", "storage"],
            ),
        )
        for identity, model in (
            ("sales", "default-model"),
            ("support", "explicit-model"),
        ):
            await host.configure_chat_model(
                "context-provider",
                model,
                workspace_id=identity,
            )
            await host.configure_tool(
                "author_workspace_probe",
                {"marker": identity},
                workspace_id=identity,
            )
        for count in range(2):
            for identity in ("sales", "support"):
                result = await host.call_tool(
                    "author_workspace_probe",
                    {},
                    workspace_id=identity,
                    session_id="shared-session",
                )
                assert json.loads(result.content[0].text) == {
                    "workspace": identity,
                    "count": count,
                    "setting": identity,
                    "text": "first:last",
                }
        for identity, model in (
            ("sales", "default-model"),
            ("support", "explicit-model"),
        ):
            request = provider.storage.read_json(
                identity + "-shared-session.json",
            )
            assert request["workspace"] == identity
            assert request["session"] == "shared-session"
            assert request["model"] == model
        assert provider.storage.read_json("shared-shared-session.json") is None
