# -*- coding: utf-8 -*-
"""Strict external-author typing: returned streams can always be closed."""

from pathlib import Path
from typing import Any, AsyncGenerator, Literal, assert_type

from qwenpaw.plugins.harnesses import HarnessBackend, HarnessCallContext

from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.apps import AppContext, ChatRequest, TaskSnapshot
from qwenpaw.plugins.cli import CliContext
from qwenpaw.plugins.context import RequestContext
from qwenpaw.plugins.drivers import DriverContext, DriverRequestContext
from qwenpaw.plugins.events import ChatEvent
from qwenpaw.plugins.providers import ModelChunk
from qwenpaw.plugins.testing import PluginTestHost, TestModel
from qwenpaw.plugins.tools import ToolEvent, ToolContext


async def channel_worker_contract() -> None:
    from qwenpaw.plugins.channel_workers import (
        ChannelDriver,
        ChannelWorkerContext,
        ChannelResponse,
        ChannelContent,
        ChannelSendResult,
        ChannelDeliveryStep,
        ChannelReceiveResult,
        ChannelApprovalAction,
        ResponsePolicy,
        ReplyTarget,
    )
    from qwenpaw.plugins.channels import ChannelMessage, ChannelRunEvent
    from qwenpaw.plugins.channel_ingress import (
        ChannelIngressBinding,
        ChannelIngressSpec,
    )
    from qwenpaw.plugins.channel_management import (
        ChannelManagementRequest,
        ChannelManagementResult,
        ChannelVerification,
    )

    class Driver(ChannelDriver):
        def response_policy_for(self, target: ReplyTarget) -> ResponsePolicy:
            return ResponsePolicy(
                streaming=not bool(target.metadata.get("thread_id")),
                configured_prefix=False,
            )

        async def on_run(
            self,
            ch: ChannelWorkerContext,
            event: ChannelRunEvent,
        ) -> None:
            assert_type(event.run_id, str)
            assert_type(event.message_ids, tuple[str, ...])

        @staticmethod
        async def manage(
            request: ChannelManagementRequest,
        ) -> ChannelManagementResult:
            assert_type(request.workspace_id, str)
            assert_type(request.remaining_timeout(), float)
            request.check_cancelled()
            return ChannelVerification("credentials", "passed")

        async def start(self, ch: ChannelWorkerContext) -> None:
            assert_type(ch.workspace_id, str)
            assert_type(ch.deadline, float | None)
            assert_type(ch.ingress.path, str)
            binding = await ch.ingress.register(
                ChannelIngressSpec("127.0.0.1", 8080),
            )
            assert_type(binding, ChannelIngressBinding)
            assert_type(binding.paths, tuple[str, ...])
            assert_type(binding.verify({"header": "value"}), str)
            assert_type(binding.url(binding.paths[0]), str)
            await ch.ingress.close()
            await ch.auth.required("https://example.test/scan")
            assert_type(
                await ch.approvals.resolve(
                    ChannelApprovalAction(
                        "request-id",
                        "deny",
                        ChannelMessage(
                            "actor",
                            (),
                            session_id="s",
                            message_id="button",
                        ),
                    ),
                ),
                ChannelReceiveResult,
            )
            await ch.report_status("connected")
            assert_type(
                await ch.receive(
                    ChannelMessage("user", (), session_id="s", message_id="m"),
                ),
                ChannelReceiveResult,
            )

        async def send(
            self,
            ch: ChannelWorkerContext,
            response: ChannelResponse,
        ) -> ChannelSendResult:
            assert_type(response.previous, ChannelSendResult | None)
            assert_type(response.content, tuple[ChannelContent, ...])
            for block in response.content:
                assert_type(block.output, str | tuple[ChannelContent, ...])
                assert_type(
                    block.role,
                    Literal["message", "reasoning", "refusal", "rendered"],
                )
            step = await ch.delivery.prepare_step("create")
            assert_type(step, ChannelDeliveryStep)
            result = ChannelSendResult("platform-message")
            await ch.delivery.record_progress(step, result)
            return result

    assert_type(Driver(), Driver)
    policy = ResponsePolicy(
        text_merge_delay_ms=200,
        continue_on_delivery_error=True,
        content_source="semantic",
    )
    assert_type(policy.text_merge_delay_ms, int | None)
    assert_type(policy.continue_on_delivery_error, bool)
    assert_type(policy.content_source, Literal["rendered", "semantic"])
    assert_type(policy.configured_prefix, bool)


def workflow_contract(plugin: PluginContext) -> None:
    from typing import Mapping
    from qwenpaw.plugins.events import JSONValue
    from qwenpaw.plugins.resources import Registration
    from qwenpaw.plugins.workflows import (
        WorkflowContext,
        WorkflowSpec,
        WorkflowSchedule,
        WorkflowResult,
        WorkflowNotification,
    )

    async def report(
        call: WorkflowContext,
        values: Mapping[str, JSONValue],
    ) -> WorkflowResult:
        assert_type(call.scheduled, bool)
        assert_type(call.identity, RequestContext)
        assert_type(call.cancelled, bool)
        return WorkflowResult(
            notification=WorkflowNotification("report", "done"),
        )

    assert_type(
        plugin.register_workflow(
            WorkflowSpec("report", report, WorkflowSchedule("0 * * * *")),
        ),
        Registration,
    )


async def workflow_test_contract(host: PluginTestHost) -> None:
    from qwenpaw.plugins.workflows import WorkflowResult

    assert_type(
        await host.run_workflow("plugin:report", parameters={"scope": "one"}),
        WorkflowResult,
    )


def static_channel_contract(path: Path) -> None:
    from typing import Mapping
    from qwenpaw.plugins.events import JSONData, JSONValue
    from qwenpaw.plugins.channel_workers import (
        ChannelDefinition,
        ChannelExclusiveResource,
    )

    definition = assert_type(ChannelDefinition.load(path), ChannelDefinition)
    assert_type(definition.to_dict(), dict[str, JSONData])
    assert_type(definition.config_schema, Mapping[str, JSONValue])
    assert_type(
        definition.exclusive_resources,
        tuple[ChannelExclusiveResource, ...],
    )
    assert_type(
        ChannelExclusiveResource("example.account", ("account",)).fields,
        tuple[str, ...],
    )


def uploaded_file_contract() -> None:
    from qwenpaw.plugins.apps import (
        HttpRequest,
        HttpResponse,
        PawApp,
        UploadedFile,
        FileResponse,
    )

    app = PawApp(app_id="files")

    @app.route("/upload", methods=("POST",), body="form", max_body_bytes=1024)
    async def upload(call: AppContext, request: HttpRequest) -> HttpResponse:
        for value in request.form.get("file", ()):
            if isinstance(value, UploadedFile):
                assert_type(value.content, bytes)
                assert_type(value.size, int)
                assert_type(value.filename, str)
        return HttpResponse({"ok": True})

    @app.route("/download")
    async def download(call: AppContext, request: HttpRequest) -> FileResponse:
        return FileResponse(call.storage.path("report.txt"))


async def checkpoint_contract(call: ToolContext) -> None:
    from qwenpaw.plugins.checkpoints import (
        CheckpointEntry,
        SnapshotResult,
        RestoreResult,
    )

    assert_type(await call.checkpoints.timeline(), tuple[CheckpointEntry, ...])
    assert_type(await call.checkpoints.snapshot(name="before"), SnapshotResult)
    assert_type(await call.checkpoints.restore("target"), RestoreResult)


def terminal_contract(context: "PluginContext", call: "CliContext") -> None:
    import click
    from qwenpaw.plugins.cli import CliSpec
    from qwenpaw.plugins.doctor import (
        DOCTOR,
        DoctorContext,
        DoctorSpec,
        DoctorResult,
    )
    from qwenpaw.plugins.resources import Registration
    from qwenpaw.plugins.logging import PluginLogger

    async def operation() -> str:
        return "result"

    def legacy_check(_call: DoctorContext) -> list[str]:
        return ["ready"]

    async def status_check(_call: DoctorContext) -> list[DoctorResult]:
        return [DoctorResult("OK", "ready")]

    assert_type(call.run(operation()), str)
    assert_type(call.logger, PluginLogger)
    assert_type(
        context.register_cli(
            CliSpec("hello", lambda ctx: click.Command("hello")),
        ),
        Registration,
    )
    assert_type(
        context.register_extension(
            DOCTOR,
            DoctorSpec("hello", status_check),
        ),
        Registration,
    )

    assert_type(DoctorSpec("legacy", legacy_check), DoctorSpec)


async def close_streams(
    app: AppContext,
    host: PluginTestHost,
    model: TestModel,
) -> None:
    chat = assert_type(
        app.chat_stream(ChatRequest("hello")),
        AsyncGenerator[ChatEvent, None],
    )
    task = assert_type(
        app.task_stream("owned-run"),
        AsyncGenerator[TaskSnapshot, None],
    )
    tool = assert_type(
        host.stream_tool("echo", {}),
        AsyncGenerator[ToolEvent, None],
    )
    host_chat = assert_type(
        host.stream_chat("hello"),
        AsyncGenerator[ChatEvent, None],
    )
    model_chat = assert_type(
        model.stream(()),
        AsyncGenerator[ModelChunk, None],
    )
    for stream in (chat, task, tool, host_chat, model_chat):
        await stream.aclose()


async def delegate_workspace(app: AppContext) -> None:
    from qwenpaw.plugins.apps import WorkspaceSummary

    workspaces = assert_type(
        await app.workspaces(),
        tuple[WorkspaceSummary, ...],
    )
    for workspace in workspaces:
        assert_type(workspace.id, str)
        assert_type(workspace.name, str)
        assert_type(workspace.enabled, bool)
        async with app.for_workspace(workspace.id) as scoped:
            assert_type(scoped, AppContext)
            assert_type(scoped.workspace_id, str)


async def channel_contract(host: PluginTestHost) -> None:
    from qwenpaw.plugins.messages import Message

    assert_type(
        await host.call_control_command("/checkpoint", user_id="owner"),
        Message | None,
    )
    from qwenpaw.plugins.channels import (
        ChannelHealth,
        ChannelMessage,
        ChannelRunEvent,
        ChannelStreamEvent,
        OutgoingMessage,
    )
    from qwenpaw.plugins.messages import ContentBlock

    incoming = ChannelMessage(
        "display-sender",
        (ContentBlock(text="hello"),),
        session_id="conversation",
        acl_sender_id="platform-sender",
        message_id="platform-message",
        session_scope="group",
        is_group=True,
    )
    assert_type(incoming.message_id, str)
    await host.receive_channel("example", incoming)
    await host.set_channel_access("example", "platform-sender", allowed=True)
    await host.send_channel(
        "example",
        "outgoing",
        user_id="user",
        session_id="session",
        require_delivery=True,
    )
    assert_type(await host.health_channel("example"), ChannelHealth)

    def correlate(  # pylint: disable=unused-variable
        event: ChannelRunEvent,
        streamed: ChannelStreamEvent,
        sent: OutgoingMessage,
    ) -> None:
        assert_type(event.message_ids, tuple[str, ...])
        assert_type(event.run_id, str)
        assert_type(streamed.run_id, str)
        assert_type(sent.run_id, str)
        assert_type(sent.require_delivery, bool)


async def context_services(call: "ToolContext") -> None:
    from qwenpaw.plugins.logging import PluginLogger
    from qwenpaw.plugins.models import ModelService
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.providers import ModelToolChoice

    logger = assert_type(call.logger, PluginLogger)
    logger.info("author operation", fields={"stage": "begin", "count": 1})
    models = assert_type(call.models, ModelService)
    messages = (Message("user", (ContentBlock(text="question"),)),)
    result = assert_type(
        await models.complete(messages, options={"temperature": 0.2}),
        ModelChunk,
    )
    assert_type(result.is_last, bool)
    stream = assert_type(
        models.stream(
            messages,
            provider_id="example",
            model_id="example-model",
            tool_choice=ModelToolChoice("auto"),
            timeout=2.0,
        ),
        AsyncGenerator[ModelChunk, None],
    )
    await stream.aclose()


def custom_workspace_host(root: Path) -> PluginTestHost:
    return PluginTestHost(
        root,
        workspace_dirs={
            "sales": "sales/shared",
            "support": Path("support/shared"),
        },
    )


async def async_storage(call: ToolContext) -> None:
    from qwenpaw.plugins.messages import Attachment

    assert_type(await call.storage.aread_bytes("data.bin"), bytes)
    assert_type(await call.storage.aread_json("state.json", {}), Any)
    await call.storage.awrite_bytes("data.bin", b"data")
    await call.storage.awrite_json("state.json", {"count": 1})
    await call.storage.adelete("state.json")
    assert_type(await call.media.awrite("result.txt", b"result"), Attachment)


async def sdk_1_1_services(call: ToolContext) -> None:
    import asyncio
    from qwenpaw.plugins.context import RequestContext
    from qwenpaw.plugins.models import ModelDescription, ModelSelection
    from qwenpaw.plugins.resources import ResourceScope

    assert_type(call.identity, RequestContext)
    assert_type(call.identity.user_id, str)
    assert_type(call.workspace_ops.directory, Path)
    assert_type(
        await call.workspace_ops.project_directories(),
        tuple[Path, ...],
    )
    assert_type(await call.workspace_ops.resolve_path("file"), Path)
    from qwenpaw.plugins.events import JSONData

    assert_type(ChatEvent("response").to_dict(), dict[str, JSONData])
    assert_type(call.storage.path("state.sqlite"), Path)
    assert_type(call.storage.import_legacy("profile", "profile.json"), bool)
    assert_type(
        call.storage.import_legacy_tree("history", "history"),
        tuple[str, ...],
    )
    assert_type(await call.models.configured(), ModelSelection | None)
    assert_type(await call.models.catalog(), tuple[ModelDescription, ...])
    async with call.resources.child() as child:
        assert_type(child, ResourceScope)
        assert_type(await child.run_sync(int, "42"), int)
        process = assert_type(
            await child.async_process(["example"], tree=True),
            asyncio.subprocess.Process,
        )
        assert_type(process.pid, int)


async def stop_contract(host: PluginTestHost) -> None:
    from qwenpaw.plugins import PluginContext
    from qwenpaw.plugins.context import RequestContext
    from qwenpaw.plugins.resources import Registration
    from qwenpaw.plugins.stops import StopContext, StopResult, StopSpec

    def declare(plugin: PluginContext) -> None:
        async def decide(call: StopContext) -> StopResult:
            assert_type(call.identity, RequestContext)
            assert_type(call.iteration, int)
            return StopResult("continue", "Check the result")

        assert_type(
            plugin.register_stop(
                StopSpec(
                    "example",
                    decide,
                    lambda identity: bool(identity.session_id),
                ),
            ),
            Registration,
        )

    assert_type(await host.evaluate_stop(iteration=2), StopResult)


async def main_conversation(call: AppContext) -> None:
    from qwenpaw.plugins.conversations import ConversationMessage

    assert_type(
        await call.conversations.history(limit=12),
        tuple[ConversationMessage, ...],
    )


def shell_backend(plugin: PluginContext) -> None:
    from qwenpaw.plugins.shell import (
        ShellBackendSpec,
        ShellRequest,
        ShellResult,
    )
    from qwenpaw.plugins.resources import Registration

    async def execute(call: ToolContext, request: ShellRequest) -> ShellResult:
        assert_type(request.command, str)
        assert_type(request.cwd, str | None)
        assert_type(request.timeout, float)
        assert_type(call.identity, RequestContext)
        return ShellResult(0, "done")

    assert_type(
        plugin.register_shell_backend(
            ShellBackendSpec("example", lambda _: True, execute),
        ),
        Registration,
    )


async def select_shell_backend(call: AppContext) -> None:
    assert_type(await call.select_shell_backend("example"), None)
    assert_type(await call.select_shell_backend(None), None)


async def driver_contract(
    plugin: "PluginContext",
    app: AppContext,
    context: "DriverContext",
    request: "DriverRequestContext",
) -> None:
    from collections.abc import Mapping
    from contextlib import AbstractAsyncContextManager
    from qwenpaw.plugins.drivers import (
        DriverCallResult,
        DriverCapabilitySpec,
        DriverConnection,
        DriverCredential,
        DriverCredentialAccess,
        DriverProtocolSpec,
        DriverSource,
    )
    from qwenpaw.plugins.events import JSONValue
    from qwenpaw.plugins.resources import Registration

    class Connection:
        async def open(self) -> None:
            pass

        async def discover(
            self,
            request: "DriverRequestContext",
        ) -> tuple[DriverCapabilitySpec, ...]:
            assert_type(request.workspace_id, str)
            return (
                DriverCapabilitySpec(
                    name="echo",
                    description="Echo",
                    input_schema={"type": "object", "properties": {}},
                ),
            )

        async def invoke(
            self,
            name: str,
            arguments: Mapping[str, JSONValue],
            request: "DriverRequestContext",
        ) -> DriverCallResult:
            assert_type(name, str)
            assert_type(request.session_id, str)
            return DriverCallResult(structured_content=arguments)

        async def close(self) -> None:
            pass

    def validate(source: DriverSource) -> None:
        assert_type(source.endpoint, Mapping[str, JSONValue])
        assert_type(source.config, Mapping[str, JSONValue])

    def create(
        context: "DriverContext",
        source: DriverSource,
    ) -> DriverConnection:
        assert_type(context.source_id, str)
        assert_type(source.protocol, str)
        return Connection()

    spec = DriverProtocolSpec(
        protocol="example",
        validate=validate,
        create=create,
    )
    registration = assert_type(
        plugin.register_driver_protocol(spec),
        Registration,
    )
    connection = assert_type(
        spec.create(context, context.source),
        DriverConnection,
    )
    await connection.open()
    capabilities = assert_type(
        await connection.discover(request),
        tuple[DriverCapabilitySpec, ...],
    )
    result = assert_type(
        await connection.invoke(capabilities[0].name, {}, request),
        DriverCallResult,
    )
    assert_type(result.structured_content, JSONValue)
    assert_type(request.workspace_instance_id, str)
    assert_type(request.user_id, str)
    assert_type(request.channel, str)
    assert_type(request.deadline, float | None)
    assert_type(request.cancelled, bool)
    request.check_cancelled()
    assert_type(context.plugin_id, str)
    assert_type(context.generation, int)
    assert_type(context.workspace_id, str)
    assert_type(context.workspace_instance_id, str)
    assert_type(context.source_id, str)
    assert_type(context.source_revision, int)
    assert_type(context.session_scope, str)
    assert_type(context.credentials, DriverCredentialAccess)
    assert_type(context.credentials.aliases, tuple[str, ...])
    assert_type(
        await context.credentials.resolve_runtime("oauth"),
        Mapping[str, JSONValue],
    )
    assert_type(await context.subprocess_environment(), Mapping[str, str])
    credential = assert_type(
        await context.credentials.resolve("oauth"),
        DriverCredential,
    )
    assert_type(credential.revision, int)
    assert_type(credential.public, Mapping[str, JSONValue])
    assert_type(credential.secrets, Mapping[str, JSONValue])
    await context.credentials.update(
        "oauth",
        expected_revision=credential.revision,
        public={"scope": "tools"},
        secrets={"token": "author-test-token"},
    )
    context.invalidate_capabilities()
    scope = assert_type(
        app.driver_source("example", "configured-source"),
        AbstractAsyncContextManager["DriverContext"],
    )
    async with scope as managed:
        assert_type(managed, DriverContext)
    await connection.close()
    await registration.close()


async def transcription_contract(host: PluginTestHost) -> None:
    from qwenpaw.plugins.transcription import (
        TranscriptionResult,
        TranscriptionStatus,
    )

    assert_type(
        await host.transcribe("local_whisper", "/audio.wav"),
        TranscriptionResult,
    )
    assert_type(
        await host.transcription_status("local_whisper"),
        TranscriptionStatus,
    )


async def harness_contract(
    plugin: PluginContext,
    backend: HarnessBackend,
    call: HarnessCallContext,
) -> None:
    from collections.abc import AsyncIterator
    from qwenpaw.plugins.harnesses import (
        HarnessCapabilities,
        HarnessContext,
        HarnessEvent,
        HarnessHistoryItem,
        HarnessModel,
        HarnessRunRequest,
        HarnessSpec,
        HarnessStatus,
    )
    from qwenpaw.plugins.resources import Registration

    def create(
        context: HarnessContext,
        settings: dict[str, Any],
    ) -> HarnessBackend:
        assert_type(context.workspace_id, str)
        assert_type(settings, dict[str, Any])
        return backend

    spec = HarnessSpec(
        "author-example",
        "Example",
        create,
        HarnessCapabilities(),
        instance_settings_keys=("binary",),
    )
    assert_type(spec.instance_settings_keys, tuple[str, ...])
    handle = assert_type(
        plugin.register_harness(spec),
        Registration,
    )
    assert_type(await backend.status(call), HarnessStatus)
    assert_type(await backend.models(call), tuple[HarnessModel, ...])
    assert_type(await backend.history(call), tuple[HarnessHistoryItem, ...])
    events = assert_type(
        backend.run_turn(call, HarnessRunRequest("hello")),
        AsyncIterator[HarnessEvent],
    )
    async for event in events:
        assert_type(event.text, str)
    await handle.close()


async def harness_author_host(host: PluginTestHost) -> None:
    from qwenpaw.plugins.harnesses import HarnessRunRequest, HarnessStatus

    assert_type(host.list_harnesses(), tuple[dict[str, Any], ...])
    assert_type(
        await host.harness_status("author-example", workspace_id="one"),
        HarnessStatus,
    )
    events = assert_type(
        host.run_harness(
            "author-example",
            HarnessRunRequest("hello"),
            workspace_id="one",
            session_id="session",
            user_id="user",
            channel="console",
        ),
        AsyncGenerator[ChatEvent, None],
    )
    await events.aclose()


async def rejected_author_usage(tool: ToolContext, app: AppContext) -> None:
    # Strict mypy reports an unused ignore if the SDK accepts an invalid call.
    await tool.models.nonexistent()  # type: ignore[attr-defined]
    await tool.models.configured(arbitrary_user="other")  # type: ignore[call-arg]
    await tool.resources.async_process(["test"], tree="yes")  # type: ignore[arg-type]
    tool.identity.user_id = "other"  # type: ignore[misc]
    async with tool.resources.child() as child:
        child.nonexistent()  # type: ignore[attr-defined]
    await app.conversations.history(session_id="other")  # type: ignore[call-arg]


async def native_provider(context: "PluginContext") -> None:
    from contextlib import asynccontextmanager
    from qwenpaw.plugins.providers import (
        ModelInfo,
        ProviderContext,
        ProviderHandle,
        ProviderSpec,
    )

    @asynccontextmanager
    async def connect(
        call: ProviderContext,
        model_id: str,
    ) -> AsyncGenerator[str, None]:
        assert_type(call.base_url, str)
        assert_type(model_id, str)
        yield "http://127.0.0.1:8080/v1"

    provider = assert_type(
        context.register_provider(
            ProviderSpec(
                "example",
                "Example",
                protocol="openai-chat",
                connect=connect,
            ),
        ),
        ProviderHandle,
    )
    await provider.update(models=(ModelInfo("model", "Model"),))
    assert_type(await provider.select("model"), None)
    assert_type(await provider.clear_selection(), bool)
    assert_type(context.storage.path("native.bin"), Path)
