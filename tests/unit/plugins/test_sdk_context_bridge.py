# -*- coding: utf-8 -*-
"""Internal controls for bound services against the builtin model factory."""

# Inspect host ownership and cleanup state at the tested bridge boundary.
# pylint: disable=protected-access

import json
import socket
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .test_sdk_context_services import package

from .timing import WAIT_TIMEOUT


async def configure_loopback(host, base_url):
    from qwenpaw.providers.provider import ProviderInfo, ModelInfo
    from qwenpaw.providers.provider_manager import ProviderManager

    await ProviderManager.get_instance().add_custom_provider(
        ProviderInfo(
            id="context-loopback",
            name="Builtin OpenAI adapter control",
            base_url=base_url,
            api_key="sk-synthetic-loopback",
            models=[ModelInfo(id="gpt-4o-mini", name="Loopback")],
            chat_model="OpenAIChatModel",
            model_sync_mode="disabled",
        ),
    )
    assert (
        ProviderManager.get_instance()
        .get_provider("context-loopback")
        .base_url
        == base_url
    )
    await host.configure_chat_model(
        "context-loopback",
        "gpt-4o-mini",
        workspace_id="bound",
    )


async def test_bound_models_match_builtin_openai_factory_over_loopback(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.providers import ModelToolChoice
    from qwenpaw.providers.provider_manager import ProviderManager

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            requests.append(
                json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])),
                ),
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for text, final in (
                ("loopback:", False),
                ("answer", False),
                ("", True),
            ):
                chunk = {
                    "id": "builtin-loopback",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text} if text else {},
                            "finish_reason": "stop" if final else None,
                        },
                    ],
                }
                if final:
                    chunk["usage"] = {
                        "prompt_tokens": 7,
                        "completion_tokens": 4,
                        "total_tokens": 11,
                    }
                self.wfile.write(
                    ("data: " + json.dumps(chunk) + "\n\n").encode(),
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_connect = socket.socket.connect

    def loopback_only(sock, address):
        if isinstance(address, tuple):
            assert address[0] in (
                "127.0.0.1",
                "::1",
            ), "External network is forbidden"
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    source = """
from dataclasses import asdict
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import Message, ContentBlock
from qwenpaw.plugins.providers import ModelToolChoice


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            result = await call.models.complete(
                (
                    Message(
                        "user", (ContentBlock(text="question"),)
                    ),
                ),
                tool_choice=ModelToolChoice("none"),
                options={"temperature": 0.2},
            )
            return ToolResult(
                result.content,
                metadata={"usage": asdict(result.usage)},
            )

        ctx.register_tool(
            ToolSpec(
                "builtin_bound_probe",
                "real factory",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            await host.load(
                package(
                    tmp_path / "caller",
                    "builtin-model-caller",
                    source,
                    ["tools"],
                ),
            )
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            await configure_loopback(host, base_url)
            # Verify routing before allowing the real builtin client to run.
            assert (
                ProviderManager.get_instance()
                .get_provider("context-loopback")
                .base_url
                == base_url
            )
            await host.configure_chat_model(
                "context-loopback",
                "gpt-4o-mini",
                workspace_id="bound",
            )
            direct = await host.create_model(
                "context-loopback",
                "gpt-4o-mini",
                workspace_id="bound",
            )
            chunks = [
                chunk
                async for chunk in direct.stream(
                    (Message("user", (ContentBlock(text="question"),)),),
                    tool_choice=ModelToolChoice("none"),
                    options={"temperature": 0.2},
                )
            ]
            expected = "".join(
                block.text for chunk in chunks for block in chunk.content
            )
            assert expected == "loopback:answer"
            result = await host.call_tool(
                "builtin_bound_probe",
                {},
                workspace_id="bound",
            )
            assert "".join(block.text for block in result.content) == expected
            assert (
                result.metadata["usage"]["input_tokens"]
                == chunks[-1].usage.input_tokens
                == 7
            )
            assert (
                result.metadata["usage"]["output_tokens"]
                == chunks[-1].usage.output_tokens
                == 4
            )
            assert len(requests) == 2
            for key in ("model", "messages", "temperature", "tool_choice"):
                assert requests[0][key] == requests[1][key]
            assert requests[0]["model"] == "gpt-4o-mini"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


async def test_cancelled_factory_worker_closes_real_late_model_client(
    tmp_path,
    monkeypatch,
):
    import asyncio
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.providers.openai_provider import OpenAIProvider

    entered, release = threading.Event(), threading.Event()
    created = []
    original = OpenAIProvider.get_chat_model_instance

    from functools import wraps

    @wraps(original)
    def blocked_factory(provider, *args, **kwargs):
        model = original(provider, *args, **kwargs)
        if provider.id == "context-loopback":
            created.append(model)
            entered.set()
            assert release.wait(
                WAIT_TIMEOUT * 2,
            ), "Factory test gate was not released"
        return model

    def forbidden_network(*_):
        raise AssertionError(
            "A cancelled factory must not start an HTTP request",
        )

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="question"),)),)
            )
            return ToolResult(result.content)

        ctx.register_tool(
            ToolSpec(
                "late_factory_probe",
                "late factory",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            package(
                tmp_path / "caller",
                "late-factory-caller",
                source,
                ["tools"],
            ),
        )
        await configure_loopback(host, "http://127.0.0.1:9/v1")
        await host.configure_chat_model(
            "context-loopback",
            "gpt-4o-mini",
            workspace_id="bound",
        )
        monkeypatch.setattr(
            OpenAIProvider,
            "get_chat_model_instance",
            blocked_factory,
        )
        monkeypatch.setattr(socket.socket, "connect", forbidden_network)
        task = asyncio.create_task(
            host.call_tool("late_factory_probe", {}, workspace_id="bound"),
        )
        try:
            assert await asyncio.to_thread(entered.wait, WAIT_TIMEOUT)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done(), "Factory thread is still live"
            with pytest.raises(PluginBusyError):
                await host.reload("late-factory-caller")
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, WAIT_TIMEOUT)
        assert len(created) == 1
        assert created[
            0
        ].client.is_closed(), "Late factory result leaked its real AsyncClient"
        assert (
            host.resource_snapshot("late-factory-caller")["active_calls"] == 0
        )
        assert (await host.reload("late-factory-caller")).ok


async def test_closing_bound_builtin_stream_closes_real_http_transport(
    tmp_path,
    monkeypatch,
):
    import asyncio
    from qwenpaw.plugins.testing import PluginTestHost

    connected, disconnected = asyncio.Event(), asyncio.Event()
    writers, serving = [], set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        serving.add(task)
        writers.append(writer)
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode()
            length = next(
                int(line.split(":", 1)[1])
                for line in headers.split("\r\n")
                if line.lower().startswith("content-length:")
            )
            request = json.loads(await reader.readexactly(length))
            assert request["model"] == "gpt-4o-mini"
            chunk = {
                "id": "held-http",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "first"},
                        "finish_reason": None,
                    },
                ],
            }
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n",
            )
            writer.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            await writer.drain()
            connected.set()
            assert await reader.read() == b""
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()
            serving.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    original_connect = socket.socket.connect

    def loopback_only(sock, address):
        if isinstance(address, tuple):
            assert address[0] in (
                "127.0.0.1",
                "::1",
            ), "External network is forbidden"
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolEvent
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            stream = call.models.stream(
                (Message("user", (ContentBlock(text="held"),)),)
            )
            try:
                async for chunk in stream:
                    if chunk.content:
                        yield ToolEvent("delta", chunk.content)
            finally:
                await stream.aclose()

        ctx.register_tool(
            ToolSpec(
                "transport_bound_probe",
                "transport",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            await host.load(
                package(
                    tmp_path / "caller",
                    "transport-caller",
                    source,
                    ["tools"],
                ),
            )
            port = server.sockets[0].getsockname()[1]
            await configure_loopback(host, f"http://127.0.0.1:{port}/v1")
            await host.configure_chat_model(
                "context-loopback",
                "gpt-4o-mini",
                workspace_id="bound",
            )
            stream = host.stream_tool(
                "transport_bound_probe",
                {},
                workspace_id="bound",
            )
            try:
                first = await asyncio.wait_for(anext(stream), WAIT_TIMEOUT)
                assert connected.is_set() and first.content[0].text == "first"
            finally:
                await asyncio.wait_for(stream.aclose(), WAIT_TIMEOUT)
            await asyncio.wait_for(disconnected.wait(), WAIT_TIMEOUT)
            assert (
                host.resource_snapshot("transport-caller")["active_calls"] == 0
            )
            assert (await host.reload("transport-caller")).ok
    finally:
        server.close()
        await server.wait_closed()
        for writer in writers:
            writer.close()
        if serving:
            await asyncio.wait_for(
                asyncio.gather(*tuple(serving), return_exceptions=True),
                WAIT_TIMEOUT,
            )


async def test_factory_formatter_failure_closes_already_created_client(
    tmp_path,
    monkeypatch,
):
    from functools import wraps
    from qwenpaw.agents import model_factory
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.providers.openai_provider import OpenAIProvider

    created = []
    original = OpenAIProvider.get_chat_model_instance

    @wraps(original)
    def record(provider, *args, **kwargs):
        model = original(provider, *args, **kwargs)
        created.append(model)
        return model

    def broken_formatter(*args, **kwargs):
        raise RuntimeError(
            "controlled formatter failure after client construction",
        )

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="question"),)),)
            )
            return ToolResult(result.content)

        ctx.register_tool(
            ToolSpec(
                "formatter_failure_probe",
                "factory cleanup",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            await host.load(
                package(
                    tmp_path / "caller",
                    "formatter-failure-caller",
                    source,
                    ["tools"],
                ),
            )
            await configure_loopback(host, "http://127.0.0.1:9/v1")
            monkeypatch.setattr(
                OpenAIProvider,
                "get_chat_model_instance",
                record,
            )
            monkeypatch.setattr(
                model_factory,
                "_install_model_formatter",
                broken_formatter,
            )
            monkeypatch.setattr(
                socket.socket,
                "connect",
                lambda *_: pytest.fail("No network is permitted"),
            )
            with pytest.raises(
                Exception,
                match="controlled formatter failure",
            ):
                await host.call_tool(
                    "formatter_failure_probe",
                    {},
                    workspace_id="bound",
                )
            assert len(created) == 1
            assert created[
                0
            ].client.is_closed(), (
                "Factory abandoned an owned client before returning its model"
            )
            assert (
                host.resource_snapshot("formatter-failure-caller")[
                    "active_calls"
                ]
                == 0
            )
            host.assert_quiescent("formatter-failure-caller")
    finally:
        # Test-owned safety cleanup occurs only after the leak assertion.
        for model in created:
            if not model.client.is_closed():
                await model.client.close()


async def test_bound_provider_identity_uses_profile_id_not_directory_name(
    tmp_path,
):
    import shutil
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_context_services import load_services, assert_complete

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_services(host, tmp_path)
        config = load_config()
        old = config.agents.profiles["one"].workspace_dir
        custom = tmp_path / "custom-directory-name"
        shutil.copytree(old, custom)
        config.agents.profiles["one"].workspace_dir = str(custom)
        save_config(config)
        result = await host.call_tool(
            "context_model_tool",
            {},
            workspace_id="one",
            session_id="identity",
        )
        assert_complete(result.metadata["result"])
        request = provider.storage.read_json("one-identity.json")
        assert request["workspace"] == "one"
        assert request["session"] == "identity"
        assert not provider.storage.read_json(
            "custom-directory-name-identity.json",
        )


async def test_real_log_formatters_preserve_bound_identity_and_author_fields(
    tmp_path,
    caplog,
):
    import logging
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.utils.logging import ColorFormatter, PlainFormatter

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        async def invoke(call, args):
            call.logger.warning(
                "visible-context-record",
                fields={
                    "plugin_id": "author-collision",
                    "business": "visible-value",
                },
            )
            return ToolResult.text("logged")

        ctx.register_tool(
            ToolSpec(
                "visible_log_probe",
                "log",
                {"type": "object"},
                invoke,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="qwenpaw")
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            package(
                tmp_path / "caller",
                "visible-log-owner",
                source,
                ["tools", "logging"],
            ),
        )
        await host.call_tool(
            "visible_log_probe",
            {},
            workspace_id="visible-workspace",
            session_id="visible-session",
        )
        record = next(
            r
            for r in caplog.records
            if r.getMessage() == "visible-context-record"
        )
        assert record.sdk_context["plugin_id"] == "visible-log-owner"
        assert record.sdk_fields["plugin_id"] == "author-collision"
        for formatter in (ColorFormatter(), PlainFormatter()):
            text = formatter.format(record)
            for value in (
                "visible-context-record",
                "visible-log-owner",
                "visible-workspace",
                "visible-session",
                "author-collision",
                "visible-value",
            ):
                assert value in text


async def test_skipped_fallback_formatter_closes_its_created_client(
    tmp_path,
    monkeypatch,
):
    from functools import wraps
    from qwenpaw.agents import model_factory
    from qwenpaw.config.config import (
        load_agent_config,
        save_agent_config,
        ModelSlotConfig,
    )
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from .test_sdk_context_services import load_services, assert_complete

    created = []
    original = OpenAIProvider.get_chat_model_instance
    formatter = model_factory._install_model_formatter

    @wraps(original)
    def record(provider, *args, **kwargs):
        result = original(provider, *args, **kwargs)
        created.append(result)
        return result

    def fail_fallback(model, *, provider_id, **kwargs):
        if provider_id == "context-loopback":
            raise RuntimeError("controlled fallback formatter failure")
        return formatter(model, provider_id=provider_id, **kwargs)

    try:
        async with PluginTestHost(tmp_path / "host") as host:
            await load_services(host, tmp_path)
            await configure_loopback(host, "http://127.0.0.1:9/v1")
            config = load_agent_config("one")
            config.fallback_models = [
                ModelSlotConfig(
                    provider_id="context-loopback",
                    model="gpt-4o-mini",
                ),
            ]
            config.fallback_policy.enabled = True
            config.fallback_policy.target_scope = "any"
            save_agent_config("one", config)
            monkeypatch.setattr(
                OpenAIProvider,
                "get_chat_model_instance",
                record,
            )
            monkeypatch.setattr(
                model_factory,
                "_install_model_formatter",
                fail_fallback,
            )
            result = await host.call_tool(
                "context_model_tool",
                {},
                workspace_id="one",
            )
            assert_complete(result.metadata["result"])
            assert len(created) == 1
            assert created[
                0
            ].client.is_closed(), (
                "Skipped fallback lost its request-owned client"
            )
    finally:
        for model in created:
            if not model.client.is_closed():
                await model.client.close()


async def test_unknown_factory_is_rejected_before_constructing_resources(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from .test_sdk_context_services import load_services

    calls = []

    def unknown_factory(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("Unknown factory must not be entered")

    async with PluginTestHost(tmp_path / "host") as host:
        await load_services(host, tmp_path)
        await configure_loopback(host, "http://127.0.0.1:9/v1")
        monkeypatch.setattr(
            OpenAIProvider,
            "get_chat_model_instance",
            unknown_factory,
        )
        with pytest.raises(SDKError):
            await host.call_tool(
                "context_model_tool",
                {},
                workspace_id="bound",
            )
        assert not calls
        assert (await host.reload("context-caller-plugin")).ok


@pytest.mark.parametrize("use_model", [False, True])
async def test_published_tool_uses_real_profile_with_shared_directory_basename(
    tmp_path,
    use_model,
    caplog,
):
    # Keep this ownership/cleanup scenario and its assertions together.
    # pylint: disable=too-many-statements
    import shutil
    from agentscope.permission import PermissionBehavior
    from agentscope.tool import ToolResponse
    from qwenpaw.agents import tools
    from qwenpaw.config.context import (
        current_workspace_dir,
        current_session_id,
    )
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.governance.tool_adapter import PolicyGuardedTool
    from qwenpaw.governance.resource_governor import ResourceGovernor
    from qwenpaw.governance.policy import GovernanceRule, GovernanceAction
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_context_services import PROVIDER

    source = """
import json
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def probe(call, args):
            before = call.storage.read_json("counter.json", 0)
            call.storage.write_json("counter.json", before + 1)
            call.logger.warning(
                "workspace-identity",
                fields={"actual": call.workspace_id},
            )
            if args.get("model"):
                await call.models.complete(
                    (
                        Message(
                            "user", (ContentBlock(text="identity"),)
                        ),
                    )
                )
            return ToolResult.text(
                json.dumps(
                    {
                        "workspace": call.workspace_id,
                        "before": before,
                        "setting": call.config.get("marker"),
                    }
                )
            )

        ctx.register_tool(
            ToolSpec(
                "profile_identity_probe",
                "identity",
                {
                    "type": "object",
                    "properties": {"model": {"type": "boolean"}},
                },
                probe,
                enabled=True,
                config_fields=({"name": "marker", "type": "text"},),
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "identity-provider",
                PROVIDER,
                ["providers"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "identity-caller",
                source,
                ["tools", "storage"],
            ),
        )
        for identity in ("sales", "support"):
            await host.configure_chat_model(
                "context-provider",
                "default-model" if identity == "sales" else "explicit-model",
                workspace_id=identity,
            )
            await host.configure_tool(
                "profile_identity_probe",
                {"marker": identity},
                workspace_id=identity,
            )
        config = load_config()
        directories = {}
        for identity in ("sales", "support"):
            directory = tmp_path / identity / "shared"
            shutil.copytree(
                config.agents.profiles[identity].workspace_dir,
                directory,
            )
            config.agents.profiles[identity].workspace_dir = str(directory)
            directories[identity] = directory
        save_config(config)
        observed = []
        for identity in ("sales", "support", "sales", "support"):
            directory = directories[identity]
            governor = ResourceGovernor(
                str(directory),
                governance_dir=str(host.root / "governance"),
            )
            governor.start()
            governor.policy.user_rules.insert(
                0,
                GovernanceRule("*(**)", GovernanceAction.ALLOW),
            )
            tool = PolicyGuardedTool(
                tools.profile_identity_probe,
                governor=governor,
                request_context={
                    "agent_id": identity,
                    "session_id": "same-session",
                },
            )
            assert (
                await tool.check_permissions({"model": use_model})
            ).behavior is PermissionBehavior.ALLOW
            response = ToolResponse()
            workspace_token = current_workspace_dir.set(directory)
            session_token = current_session_id.set("same-session")
            try:
                # PolicyGuardedTool forwards calls to the registered handler.
                stream = await tool(  # pylint: disable=not-callable
                    model=use_model,
                )
                try:
                    async for chunk in stream:
                        response.append_chunk(chunk)
                finally:
                    await stream.aclose()
            finally:
                current_session_id.reset(session_token)
                current_workspace_dir.reset(workspace_token)
            observed.append(
                json.loads("".join(block.text for block in response.content)),
            )
        assert observed == [
            {"workspace": identity, "before": before, "setting": identity}
            for before in (0, 1)
            for identity in ("sales", "support")
        ]
        assert [
            record.sdk_context["workspace_id"]
            for record in caplog.records
            if record.getMessage() == "workspace-identity"
        ] == ["sales", "support", "sales", "support"]
        if use_model:
            for identity, model in (
                ("sales", "default-model"),
                ("support", "explicit-model"),
            ):
                request = provider.storage.read_json(
                    identity + "-same-session.json",
                )
                assert request["workspace"] == identity
                assert request["model"] == model
            assert (
                provider.storage.read_json("shared-same-session.json") is None
            )


MODEL_CLEANUP_REFUSAL = """
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            async def cleanup():
                ctx.storage.write_json(
                    "attempts.json",
                    ctx.storage.read_json("attempts.json", 0) + 1,
                )
                if not ctx.storage.read_json("release.json", False):
                    raise RuntimeError("controlled cleanup refusal")
                ctx.storage.write_json("closed.json", True)

            call.resources.defer(cleanup, "retained model cleanup")
            yield ModelChunk(
                (ContentBlock(text="result"),), is_last=True
            )

        ctx.register_provider(
            ProviderSpec(
                "bound-provider",
                "Bound",
                generate,
                models=(ModelInfo("bound-model", "Bound"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""


@pytest.mark.parametrize("interrupt_retry", [False, True])
@pytest.mark.usefixtures("short_stream_stop_timeout")
async def test_interrupt_reload_retries_cleanup_after_outer_tool_exits(
    tmp_path,
    interrupt_retry,
):
    import asyncio
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_context_lifecycle import load_pair, until

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_pair(host, tmp_path, MODEL_CLEANUP_REFUSAL)
        call = asyncio.create_task(
            host.call_tool("bound_complete", {}, workspace_id="bound"),
        )
        try:
            await until(
                lambda: provider.storage.read_json("attempts.json", 0) > 0,
            )
            with pytest.raises(PluginBusyError):
                await host.reload("bound-caller-owner", interrupt_tasks=True)
            # Wait for the actual outer invocation, not a guessed cleanup
            # delay.
            done, _ = await asyncio.wait({call}, timeout=20)
            assert (
                call in done
            ), "The controlled case requires the outer tool to have exited"
            assert not provider.storage.read_json("closed.json", False)
            assert (
                host.resource_snapshot("bound-caller-owner")["active_calls"]
                > 0
            )
            attempts = provider.storage.read_json("attempts.json")
            provider.storage.write_json("release.json", True)
            report = await host.reload(
                "bound-caller-owner",
                interrupt_tasks=interrupt_retry,
            )
            assert report.ok
            assert provider.storage.read_json("attempts.json") > attempts
            assert provider.storage.read_json("closed.json") is True
            assert (
                host.resource_snapshot("bound-caller-owner")["active_calls"]
                == 0
            )
            assert (await host.reload("bound-provider-owner")).ok
        finally:
            # Failure-only test hygiene: these private cancellations are never
            # used to satisfy the public-retry assertions above.
            host.context("bound-provider-owner").storage.write_json(
                "release.json",
                True,
            )
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    pending = {
                        task
                        for owner in (
                            "bound-caller-owner",
                            "bound-provider-owner",
                        )
                        if (
                            instance := host._loader.lifecycle.get_instance(
                                owner,
                            )
                        )
                        for task in instance.activity.tasks
                        if not task.done()
                    }
                    if not call.done():
                        pending.add(call)
                    if not pending:
                        break
                    for task in pending:
                        task.cancel()
                    await asyncio.sleep(0.02)
            await asyncio.gather(call, return_exceptions=True)


async def test_open_model_stream_closes_after_profile_directory_changes(
    tmp_path,
):
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins.testing import PluginTestHost
    from .test_sdk_context_lifecycle import load_pair

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_pair(host, tmp_path)
        stream = host.stream_tool(
            "bound_stream",
            {},
            workspace_id="bound",
            session_id="moving-profile",
        )
        first = await anext(stream)
        assert first.content[0].text == "first"
        config = load_config()
        original = config.agents.profiles["bound"].workspace_dir
        relocated = tmp_path / "relocated-workspace"
        relocated.mkdir()
        config.agents.profiles["bound"].workspace_dir = str(relocated)
        save_config(config)
        try:
            await stream.aclose()
            assert provider.storage.read_json("provider-closed.json") is True
            assert (
                host.resource_snapshot("bound-provider-owner")["active_calls"]
                == 0
            )
            assert (
                host.resource_snapshot("bound-caller-owner")["active_calls"]
                == 0
            )
        finally:
            config = load_config()
            config.agents.profiles["bound"].workspace_dir = original
            save_config(config)
            provider.storage.write_json("release.json", True)
            await stream.aclose()


@pytest.mark.parametrize("entry", ["app", "channel"])
@pytest.mark.usefixtures("short_interrupt_timeout")
async def test_runtime_owner_retries_failed_provider_scope_via_public_reload(
    tmp_path,
    entry,
):
    import asyncio
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from .test_sdk_context_lifecycle import until

    source = """
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.channels import ChannelSpec


class Plugin:
    def register(self, plugin):
        class Backend:
            async def start(self, ctx):
                pass

            async def stop(self, ctx):
                return True

            async def send(self, ctx, message):
                pass

        plugin.register_channel(
            ChannelSpec(
                "cleanup-runtime", "Cleanup runtime", Backend
            )
        )
        plugin.register_app(
            PawApp(
                app_id="cleanup-runtime"
            ).enable_standard_capabilities()
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "runtime-cleanup-provider",
                MODEL_CLEANUP_REFUSAL,
                ["providers", "storage"],
            ),
        )
        await host.load(
            package(
                tmp_path / "caller",
                "runtime-cleanup-caller",
                source,
                ["apps", "channels"],
            ),
        )
        await host.configure_chat_model(
            "bound-provider",
            "bound-model",
            workspace_id="bound",
        )
        if entry == "app":
            response = await host.request(
                "POST",
                "/api/cleanup-runtime/tasks",
                workspace_id="bound",
                json={"message": "runtime cleanup", "session_id": "owned"},
            )
            assert response.status == 200
        else:
            await host.start_channel(
                "cleanup-runtime",
                {},
                workspace_id="bound",
            )
            await host.receive_channel(
                "cleanup-runtime",
                ChannelMessage(
                    "author",
                    (ContentBlock(text="runtime cleanup"),),
                ),
                workspace_id="bound",
            )
        try:
            await until(
                lambda: provider.storage.read_json("attempts.json", 0) > 0,
            )
            with pytest.raises(PluginBusyError):
                await host.reload(
                    "runtime-cleanup-caller",
                    interrupt_tasks=True,
                )
            assert not provider.storage.read_json("closed.json", False)
            assert (
                host.resource_snapshot("runtime-cleanup-caller")[
                    "active_calls"
                ]
                > 0
            )
            attempts = provider.storage.read_json("attempts.json")
            provider.storage.write_json("release.json", True)
            assert (
                await host.reload(
                    "runtime-cleanup-caller",
                    interrupt_tasks=True,
                )
            ).ok
            assert provider.storage.read_json("closed.json") is True
            assert provider.storage.read_json("attempts.json") > attempts
            assert (
                host.resource_snapshot("runtime-cleanup-caller")[
                    "active_calls"
                ]
                == 0
            )
            assert (await host.reload("runtime-cleanup-provider")).ok
        finally:
            host.context("runtime-cleanup-provider").storage.write_json(
                "release.json",
                True,
            )
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    pending = {
                        task
                        for owner in (
                            "runtime-cleanup-caller",
                            "runtime-cleanup-provider",
                        )
                        if (
                            instance := host._loader.lifecycle.get_instance(
                                owner,
                            )
                        )
                        for task in instance.activity.tasks
                        if not task.done()
                    }
                    if not pending:
                        break
                    for task in pending:
                        task.cancel()
                    await asyncio.sleep(0.02)
