# -*- coding: utf-8 -*-
"""Core Qoder scenarios using its real SDK above a local CLI transport."""

import asyncio
import base64
import json
import zipfile
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qoder_agent_sdk import (
    PermissionResultDeny,
    ToolPermissionContext,
    Transport,
)
from qoder_agent_sdk._internal.sessions import _get_project_dir
from qwenpaw.app.chats.api import (
    ChatForkRequest,
    fork_chat_at_turn,
    get_fork_capability,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.plugins.harnesses import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessEventKind,
    HarnessMCPServerDefinition,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
    HarnessSkillDefinition,
)
from qwenpaw.plugins.resources import ResourceOwner, ResourceScope
from qwenpaw.plugins.storage import PluginStorage
from qwenpaw.plugins.testing import PluginTestHost
from plugins.harness.qoder.adapter import QoderBackend
from plugins.harness.qoder.discovery import (
    bundled_cli_candidate,
    resolve_qoder_binary_info,
)


class QoderTransport(Transport):
    """Record CLI inputs and answer the SDK control/stream protocol."""

    def __init__(self, *, prompt, options):
        del prompt
        self.options, self.inputs, self.decisions = options, [], []
        self.messages, self.closed = asyncio.Queue(), False
        self.native_id = options.resume or options.session_id or "temporary"
        self.interrupted = asyncio.Event()

    async def connect(self):
        pass

    def result(self, *, failed=False):
        if not failed:
            project = _get_project_dir(str(self.options.cwd.resolve()))
            project.mkdir(parents=True, exist_ok=True)
            path = project / f"{self.native_id}.jsonl"
            entries = (
                [json.loads(line) for line in path.read_text().splitlines()]
                if path.exists()
                else []
            )
            parent = next(
                (e["uuid"] for e in reversed(entries) if "uuid" in e),
                None,
            )
            entry = {
                "type": "assistant",
                "uuid": str(uuid.uuid4()),
                "parentUuid": parent,
                "sessionId": self.native_id,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Done"},
                    ],
                    "stop_reason": "end_turn",
                },
            }
            with path.open("a") as stream:
                stream.write(json.dumps(entry) + "\n")
        return {
            "type": "result",
            "subtype": "error_during_execution" if failed else "success",
            "duration_ms": 1,
            "duration_api_ms": 1,
            "is_error": failed,
            "num_turns": 1,
            "session_id": self.native_id,
            "result": "Vendor turn failed" if failed else "",
        }

    def emit(self, kind, **payload):
        self.messages.put_nowait({"type": kind, **payload})

    async def write(self, data):
        message = json.loads(data)
        if message["type"] == "control_request":
            self.control(message)
        elif message["type"] == "control_response":
            self.decisions.append(message["response"]["response"])
            self.messages.put_nowait(self.result())
        elif message["type"] == "user":
            self.inputs.append(message)
            self.respond(message["message"]["content"])

    def control(self, message):
        subtype = message["request"]["subtype"]
        response = {"skills": [{"name": "docs", "source": "user"}]}
        if subtype == "get_models":
            response = {"models": [{"value": "qoder-test", "isEnabled": True}]}
        elif subtype == "interrupt":
            self.messages.put_nowait(self.result(failed=True))
            self.interrupted.set()
        self.emit(
            "control_response",
            response={
                "subtype": "success",
                "request_id": message["request_id"],
                "response": response,
            },
        )

    def respond(self, prompt):
        if prompt == "approve":
            permission = {
                "subtype": "can_use_tool",
                "tool_name": "Bash",
                "input": {"command": "pytest"},
                "tool_use_id": "tool",
                "display_name": "Shell",
            }
            self.emit(
                "control_request",
                request_id="permission-1",
                request=permission,
            )
            return
        content = [
            {
                "type": "text",
                "text": "Working" if prompt == "wait" else "Done",
            },
            {
                "type": "tool_use",
                "id": "tool",
                "name": "Bash",
                "input": {"command": "pytest"},
            },
        ]
        self.emit(
            "assistant",
            message={"model": "qoder-test", "content": content},
        )
        if prompt != "wait":
            output = {
                "type": "tool_result",
                "tool_use_id": "tool",
                "content": "1 passed",
            }
            self.emit("user", message={"content": [output]})
            self.messages.put_nowait(self.result(failed=prompt == "fail"))

    async def read_messages(self):
        while True:
            yield await self.messages.get()

    async def close(self):
        self.closed = True

    def is_ready(self):
        return not self.closed

    async def end_input(self):
        pass


@pytest.fixture(name="runtime")
async def make_runtime(tmp_path, monkeypatch):
    binary = tmp_path / "qodercli"
    binary.touch()
    binary.chmod(0o755)
    monkeypatch.setenv("QODERCLI_PATH", str(binary))
    monkeypatch.setenv("QODER_CONFIG_DIR", str(tmp_path / "vendor"))
    monkeypatch.delenv("QODER_PERSONAL_ACCESS_TOKEN", raising=False)
    state = tmp_path / "workspace" / "plugin-data" / "qwenpaw-harness-qoder"
    state.mkdir(parents=True)
    owner = ResourceOwner("qwenpaw-harness-qoder", 1, "workspace")
    context = HarnessContext(
        owner.plugin_id,
        1,
        "workspace",
        state.parents[1],
        state,
        PluginStorage(state, lambda: None),
        ResourceScope(owner, lambda: None),
        SimpleNamespace(),
    )
    transports, backends = [], []

    def transport(**kwargs):
        value = QoderTransport(**kwargs)
        transports.append(value)
        return value

    monkeypatch.setattr(
        "qoder_agent_sdk._internal.transport.subprocess_cli."
        "SubprocessCLITransport",
        transport,
    )
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (
        b"Username: tester\nEmail: a@example.test",
        b"",
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )

    def backend():
        value = QoderBackend(context, binary=str(binary))
        backends.append(value)
        return value

    def call(user="alice", session="chat", **kwargs):
        return HarnessCallContext(
            f"{user}-{session}",
            session,
            user,
            "console",
            context.workspace_dir,
            {},
            None,
            context.resources.child(instance_id="call"),
            **kwargs,
        )

    yield SimpleNamespace(
        context=context,
        call=call,
        backend=backend,
        transports=transports,
        binary=binary,
    )
    for value in backends:
        await value.close()


async def collect(backend, call, prompt="Continue", attachments=()):
    request = HarnessRunRequest(prompt, attachments)
    async with asyncio.timeout(3):
        return [event async for event in backend.run_turn(call, request)]


async def test_discovery_accounts_and_models(runtime):
    assert bundled_cli_candidate().is_file()
    assert (
        resolve_qoder_binary_info(str(runtime.binary)).source == "configured"
    )
    backend, call = runtime.backend(), runtime.call()
    status = await backend.status(call)
    assert status.installed and status.authenticated
    assert status.account == {
        "type": "qodercli",
        "username": "tester",
        "email": "a@example.test",
    }
    models = await backend.models(call)
    assert [(model.id, model.is_default) for model in models] == [
        ("qoder-test", True),
    ]
    assert runtime.transports[-1].closed
    missing = QoderBackend(
        runtime.context,
        binary=str(runtime.binary.parent / "missing"),
    )
    try:
        unavailable = await missing.status(call)
        assert (
            unavailable.installed is False and "not found" in unavailable.error
        )
    finally:
        await missing.close()


@pytest.mark.parametrize("failed", [False, True])
async def test_turn_model_permissions_and_events(runtime, failed):
    backend = runtime.backend()
    call = replace(
        runtime.call(),
        settings={
            "model": "qoder-test",
            "reasoning_effort": "high",
            "permission_mode": "plan",
        },
    )
    events = await collect(backend, call, "fail" if failed else "Review")
    assert [e.kind for e in events] == [
        HarnessEventKind.SESSION_BOUND,
        HarnessEventKind.TEXT_DELTA,
        HarnessEventKind.TOOL_STARTED,
        HarnessEventKind.TOOL_COMPLETED,
        *([] if failed else [HarnessEventKind.TURN_BOUNDARY]),
        HarnessEventKind.ERROR if failed else HarnessEventKind.COMPLETED,
    ]
    assert events[1].text == "Done"
    assert (events[2].tool_name, events[2].data["arguments"]) == (
        "Bash",
        {"command": "pytest"},
    )
    assert events[3].text == "1 passed"
    if failed:
        assert events[-1].text == "Vendor turn failed"
    options = runtime.transports[-1].options
    assert options.model == "qoder-test" and options.extra_args == {
        "reasoning-effort": "high",
    }
    assert (
        options.permission_mode == "plan"
        and not options.allow_dangerously_skip_permissions
    )


async def test_skills_mcp_scope_credentials_and_attachments(runtime):
    backend, call = runtime.backend(), runtime.call()
    skill = call.cwd / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: review\n---\n")
    image, document = call.cwd / "screen.png", call.cwd / "notes.txt"
    image.write_bytes(b"image")
    document.write_text("notes")
    capabilities = HarnessRuntimeCapabilities(
        skills=(HarnessSkillDefinition("review", skill),),
        mcp_servers=(
            HarnessMCPServerDefinition(
                "docs",
                "Docs",
                "streamable_http",
                url="https://mcp.example.test",
                headers={"Authorization": "Bearer secret"},
                tools=("search",),
                tool_policies={"search": "ask"},
            ),
        ),
    )
    await collect(
        backend,
        replace(call, runtime_capabilities=capabilities),
        "Review",
        (
            HarnessAttachment(HarnessAttachmentKind.IMAGE, image),
            HarnessAttachment(HarnessAttachmentKind.FILE, document),
        ),
    )
    transport = runtime.transports[-1]
    options = transport.options
    assert (
        options.allowed_mcp_server_names == ["docs"]
        and options.strict_mcp_config
    )
    assert options.mcp_servers["docs"]["headers"] == {
        "Authorization": "Bearer secret",
    }
    assert options.mcp_servers["docs"]["tools"] == [
        {"name": "search", "permission_policy": "always_ask"},
    ]
    projected = Path(options.plugins[0]["path"])
    assert projected.is_relative_to(runtime.context.state_dir)
    assert (projected / "skills" / "review" / "SKILL.md").read_text() == (
        skill / "SKILL.md"
    ).read_text()
    content = transport.inputs[0]["message"]["content"]
    assert content[0] == {"type": "text", "text": "@notes.txt\nReview"}
    assert content[1]["source"]["data"] == base64.b64encode(b"image").decode()
    skills = await backend.discover_skills(call)
    assert [(s.name, s.provider_id, s.read_only) for s in skills] == [
        ("docs", "qoder", True),
    ]
    assert runtime.transports[-1].options.setting_sources == [
        "user",
        "project",
        "local",
    ]


async def test_legacy_session_reopens_reads_and_clears_without_crossing_users(
    runtime,
):
    native = "550e8400-e29b-41d4-a716-446655440000"
    old = runtime.context.workspace_dir / "harnesses" / "qoder_sessions.json"
    old.parent.mkdir()
    old.write_text(json.dumps({"chat": native}))
    first, call = runtime.backend(), runtime.call()
    events = await collect(first, call)
    assert runtime.transports[-1].options.resume == native
    await first.close()
    second = runtime.backend()
    await collect(second, call)
    assert runtime.transports[-1].options.resume == native
    await collect(second, runtime.call("bob"))
    assert runtime.transports[-1].options.resume is None
    assert runtime.transports[-1].options.session_id != native
    boundary = next(
        e.data for e in events if e.kind == HarnessEventKind.TURN_BOUNDARY
    )
    child = await second.fork_session(call, boundary=boundary)
    fork_call = runtime.call(session="fork-child")
    await second.bind_session(fork_call, child)
    continued = await collect(second, fork_call)
    assert runtime.transports[-1].options.resume == child
    child_boundary = next(
        e.data for e in continued if e.kind == HarnessEventKind.TURN_BOUNDARY
    )
    grandchild = await second.fork_session(fork_call, boundary=child_boundary)
    assert grandchild not in {child, native}
    project = _get_project_dir(str(call.cwd.resolve()))
    project.mkdir(parents=True, exist_ok=True)
    transcript = project / f"{native}.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "answer",
                "parentUuid": None,
                "sessionId": native,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Recovered"}],
                },
            },
        )
        + "\n",
    )
    assert [item.text for item in await second.history(call)] == ["Recovered"]
    await second.reset_session(call)
    assert transcript.exists() and await second.history(call) == ()
    await collect(second, call)
    assert runtime.transports[-1].options.session_id != native
    assert old.read_text() == json.dumps({"chat": native})


@pytest.mark.parametrize(
    ("outcome", "behavior"),
    [("approved", "allow"), ("rejected", "deny")],
)
async def test_approval_belongs_to_live_call(runtime, outcome, behavior):
    seen = []

    async def decide(summary, *, timeout):
        seen.append(
            (
                summary.tool_name,
                summary.parameters["provider_item_id"],
                timeout,
            ),
        )
        return outcome

    backend = runtime.backend()
    call = runtime.call(_request_approval=decide)
    assert (await collect(backend, call, "approve"))[
        -1
    ].kind == HarnessEventKind.COMPLETED
    first = runtime.transports[-1]
    assert first.decisions[0]["behavior"] == behavior
    assert first.decisions[0]["toolUseID"] == "tool"
    assert seen == [("Bash", "tool", 60)]
    bob = backend.run_turn(runtime.call("bob"), HarnessRunRequest("wait"))
    try:
        assert (await anext(bob)).kind == HarnessEventKind.SESSION_BOUND
        assert (await anext(bob)).kind == HarnessEventKind.TEXT_DELTA
        stale = await first.options.can_use_tool(
            "Bash",
            {},
            ToolPermissionContext(),
        )
        assert isinstance(stale, PermissionResultDeny)
        assert seen == [("Bash", "tool", 60)]
    finally:
        await bob.aclose()


async def test_cancel_then_continue_drops_old_result_and_closes_transport(
    runtime,
):
    backend, call = runtime.backend(), runtime.call()
    ready = asyncio.Event()

    async def consume():
        async for event in backend.run_turn(call, HarnessRunRequest("wait")):
            if event.kind == HarnessEventKind.TEXT_DELTA:
                ready.set()

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(ready.wait(), 2)
        old = runtime.transports[-1]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert old.interrupted.is_set() and old.closed
        events = await collect(backend, call)
        assert events[-1].kind == HarnessEventKind.COMPLETED
        assert [
            e.text for e in events if e.kind == HarnessEventKind.TEXT_DELTA
        ] == [
            "Done",
        ]
        current = runtime.transports[-1]
        assert current is not old and current.options.resume == old.native_id
        await backend.close()
        assert current.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_actual_zip_manifest_registration_and_host_call(
    runtime,
    tmp_path,
):
    plugin_id = "qwenpaw-harness-qoder"
    archive = Path(__file__).resolve().parents[4] / (
        f"dist/plugins/harness/{plugin_id}/{plugin_id}-1.0.0.zip"
    )
    assert (
        archive.is_file()
    ), "Build and package Harness plugins before vendor tests"
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(tmp_path / "unpacked")
    source = tmp_path / "unpacked" / plugin_id
    manifest = json.loads((source / "plugin.json").read_text())
    assert (
        manifest["id"] == plugin_id
        and manifest["entry"]["backend"] == "main.py"
    )
    assert (source / manifest["entry"]["frontend"]).is_file()
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok
        assert [
            (r["id"], r["plugin_id"], r["status"])
            for r in host.list_harnesses()
        ] == [
            ("qoder", plugin_id, "available"),
        ]
        output = [
            item
            async for item in host.run_harness(
                "qoder",
                HarnessRunRequest("Review"),
                workspace_id="test",
                session_id="zip-call",
            )
        ]
        assert output[-1].status == "completed", output[-1]
        assert "Done" in str(output) and "1 passed" in str(output)
        assert (
            runtime.transports[-1].inputs[0]["message"]["content"] == "Review"
        )

        workspace = await host._workspace("test")
        parent = await workspace.chat_manager.create_chat(
            ChatSpec(
                name="Native fork",
                session_id="zip-call",
                user_id="test",
                channel="console",
            ),
        )
        for _ in range(2):
            state = workspace.transcript_store.read_provider_state(
                session_id=parent.session_id,
                user_id=parent.user_id,
                channel=parent.channel,
            )
            turn_id = list(state["boundaries"])[-1]
            capability = await get_fork_capability(
                parent.id,
                turn_id,
                workspace.chat_manager,
                workspace,
            )
            assert capability == {"can_fork": True, "reason": None}
            child = await fork_chat_at_turn(
                parent.id,
                ChatForkRequest(turn_id=turn_id),
                workspace.chat_manager,
                workspace,
            )
            assert child.parent_chat_id == parent.id
            output = [
                item
                async for item in host.run_harness(
                    "qoder",
                    HarnessRunRequest("Continue"),
                    workspace_id="test",
                    session_id=child.session_id,
                )
            ]
            assert output[-1].status == "completed", output[-1]
            parent = child
