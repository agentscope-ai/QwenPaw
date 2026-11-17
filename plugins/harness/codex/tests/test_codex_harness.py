# -*- coding: utf-8 -*-
"""Core Codex protocol scenarios; only the CLI process is replaced."""

import asyncio
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
from plugins.harness.codex.adapter import CodexBackend
from plugins.harness.codex.app_server import CodexAppServerClient
from plugins.harness.codex.discovery import (
    bundled_cli_candidate,
    resolve_codex_binary_info,
)


class CodexProcess:
    """JSON lines at the process boundary, consumed by the real RPC client."""

    def __init__(self, args, environment):
        self.args, self.environment = args, environment
        self.requests, self.decisions = [], []
        self.lines, self.exited = asyncio.Queue(), asyncio.Event()
        self.returncode, self.stderr, self.counter = None, None, 0
        self.current = {}
        self.stdout = SimpleNamespace(readline=self.lines.get)
        self.stdin = SimpleNamespace(write=self.write, drain=AsyncMock())

    def emit(self, message):
        self.lines.put_nowait(json.dumps(message).encode() + b"\n")

    def notify(self, method, **params):
        self.emit({"method": method, "params": {**self.current, **params}})

    def complete(self, *, failed=False):
        self.notify(
            "turn/completed",
            turn={
                "id": self.current["turnId"],
                "status": "failed" if failed else "completed",
                "error": {"message": "Vendor turn failed"},
            },
        )

    def write(self, data):
        message = json.loads(data)
        if "method" not in message:
            self.decisions.append(message["result"])
            self.complete()
            return
        method, params = message["method"], message.get("params", {})
        self.requests.append((method, params))
        if "id" not in message:
            return
        response = {}
        if method == "account/read":
            response = {
                "account": {
                    "type": "chatgpt",
                    "email": "a@example.test",
                    "accessToken": "private",
                },
            }
        elif method == "account/login/start":
            response = {"authUrl": "https://login.example.test"}
        elif method == "model/list":
            response = {"data": [{"model": "gpt-test"}]}
        elif method == "skills/list":
            response = {
                "data": [{"skills": [{"name": "docs", "scope": "user"}]}],
            }
        elif method == "thread/start":
            self.counter += 1
            response = {"thread": {"id": f"new-{self.counter}"}}
        elif method == "thread/resume":
            response = {"thread": {"id": params["threadId"]}}
        elif method == "thread/read":
            user = {
                "id": "u",
                "type": "userMessage",
                "content": [{"type": "text", "text": "Old prompt"}],
            }
            answer = {"id": "a", "type": "agentMessage", "text": "Old answer"}
            response = {"thread": {"turns": [{"items": [user, answer]}]}}
        elif method == "turn/start":
            self.previous_turn = self.current.get("turnId", "old-turn")
            self.current = {
                "threadId": params["threadId"],
                "turnId": f"turn-{len(self.requests)}",
            }
            response = {"turn": {"id": self.current["turnId"]}}
        self.emit({"id": message["id"], "result": response})
        if method == "turn/start":
            self.start_turn(params["input"][0]["text"])

    def start_turn(self, prompt):
        if prompt == "approve":
            self.emit(
                {
                    "id": 900,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        **self.current,
                        "itemId": "tool",
                        "command": "pytest",
                    },
                },
            )
        elif prompt == "wait":
            self.notify(
                "item/agentMessage/delta",
                itemId="answer",
                delta="Working",
            )
        else:
            # A result from a cancelled native turn must not enter this turn.
            self.notify(
                "item/agentMessage/delta",
                turnId=self.previous_turn,
                delta="STALE",
            )
            self.notify(
                "item/agentMessage/delta",
                itemId="answer",
                delta="Done",
            )
            tool = {
                "id": "tool",
                "type": "commandExecution",
                "command": "pytest",
            }
            self.notify("item/started", item=tool)
            self.notify(
                "item/completed",
                item={**tool, "aggregatedOutput": "1 passed", "exitCode": 0},
            )
            self.complete(failed=prompt == "fail")

    def terminate(self):
        self.returncode = 0
        self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return self.returncode


@pytest.fixture(name="runtime")
async def make_runtime(tmp_path, monkeypatch):
    binary = tmp_path / "codex"
    binary.touch()
    binary.chmod(0o755)
    monkeypatch.setenv("CODEX_BINARY", str(binary))
    state = tmp_path / "workspace" / "plugin-data" / "qwenpaw-harness-codex"
    state.mkdir(parents=True)
    owner = ResourceOwner("qwenpaw-harness-codex", 1, "workspace")
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
    processes, backends = [], []

    async def spawn(*args, **kwargs):
        if args[1:3] == ("mcp", "list"):
            records = [
                {
                    "name": "docs",
                    "enabled": True,
                    "transport": {"type": "streamable_http"},
                },
            ]
            process = CodexProcess(args, {})
            process.terminate()
            process.communicate = AsyncMock(
                return_value=(json.dumps(records).encode(), b""),
            )
            return process
        process = CodexProcess(args, kwargs["env"])
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    def backend():
        value = CodexBackend(
            context,
            client=CodexAppServerClient(binary=str(binary)),
        )
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
        processes=processes,
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
        resolve_codex_binary_info(str(runtime.binary)).source == "configured"
    )
    backend, call = runtime.backend(), runtime.call()
    status = await backend.status(call)
    assert status.installed and status.authenticated
    assert status.account == {"type": "chatgpt", "email": "a@example.test"}
    assert (await backend.start_login(call)).data[
        "authUrl"
    ] == "https://login.example.test"
    models = await backend.models(call)
    assert [model.id for model in models] == ["gpt-test"]
    missing = CodexBackend(
        runtime.context,
        binary=str(runtime.binary.parent / "missing"),
    )
    try:
        unavailable = await missing.status(call)
        assert unavailable.installed is False and "Repair" in unavailable.error
    finally:
        await missing.close()


@pytest.mark.parametrize("failed", [False, True])
async def test_turn_settings_attachments_and_protocol_events(runtime, failed):
    backend = runtime.backend()
    call = replace(
        runtime.call(),
        settings={
            "model": "gpt-test",
            "reasoning_effort": "high",
            "sandbox": "read-only",
            "approval_policy": "on-request",
        },
    )
    image, document = call.cwd / "screen.png", call.cwd / "notes.txt"
    events = await collect(
        backend,
        call,
        "fail" if failed else "Review",
        (
            HarnessAttachment(HarnessAttachmentKind.IMAGE, image),
            HarnessAttachment(HarnessAttachmentKind.FILE, document),
        ),
    )
    assert [e.kind for e in events] == [
        HarnessEventKind.TEXT_DELTA,
        HarnessEventKind.TOOL_STARTED,
        HarnessEventKind.TOOL_COMPLETED,
        HarnessEventKind.ERROR if failed else HarnessEventKind.COMPLETED,
    ]
    assert events[0].text == "Done"
    assert (events[1].tool_name, events[1].data["arguments"]["command"]) == (
        "shell",
        "pytest",
    )
    assert events[2].text == "1 passed" and events[2].data["exit_code"] == 0
    if failed:
        assert events[-1].text == "Vendor turn failed"
    requests = dict(runtime.processes[-1].requests)
    thread, turn = requests["thread/start"], requests["turn/start"]
    assert thread["model"] == turn["model"] == "gpt-test"
    assert thread["sandbox"] == "read-only" and turn["sandboxPolicy"] == {
        "type": "readOnly",
    }
    assert thread["approvalPolicy"] == turn["approvalPolicy"] == "on-request"
    assert turn["effort"] == "high"
    assert turn["input"][1:] == [
        {"type": "localImage", "path": str(image)},
        {"type": "text", "text": f"Attached file notes.txt: {document}"},
    ]


async def test_scoped_skills_and_mcp_projection(runtime):
    backend, call = runtime.backend(), runtime.call()
    skill = call.cwd / "skills" / "review"
    capabilities = HarnessRuntimeCapabilities(
        skills=(HarnessSkillDefinition("review", skill),),
        mcp_servers=(
            HarnessMCPServerDefinition(
                "docs",
                "Docs",
                "streamable_http",
                url="https://mcp.example.test",
                headers={"Authorization": "Bearer secret"},
                tools=("read", "write"),
                tool_policies={"read": "allow", "write": "deny"},
            ),
        ),
    )
    await collect(backend, replace(call, runtime_capabilities=capabilities))
    process = runtime.processes[-1]
    assert (
        "skills/extraRoots/set",
        {"extraRoots": [str(skill)]},
    ) in process.requests
    assert "secret" not in "\n".join(process.args)
    assert "Bearer secret" in process.environment.values()
    assert any('enabled_tools=["read"]' in arg for arg in process.args)
    skills, servers = await backend.discover_skills(
        call,
    ), await backend.discover_mcp(
        call,
    )
    assert [(s.name, s.scope, s.read_only) for s in skills] == [
        ("docs", "provider", True),
    ]
    assert [(s.name, s.scope, s.read_only) for s in servers] == [
        ("docs", "provider", True),
    ]
    assert all(
        str(call.cwd) == p["cwds"][0]
        for m, p in process.requests
        if m == "skills/list"
    )


async def test_legacy_session_reopens_with_same_identity_and_clears(runtime):
    old = runtime.context.workspace_dir / "harnesses" / "codex_sessions.json"
    old.parent.mkdir()
    old.write_text('{"chat":"native-old"}')
    first, call = runtime.backend(), runtime.call()
    await collect(first, call)
    assert ("thread/resume", {"threadId": "native-old"}) in runtime.processes[
        -1
    ].requests
    await first.close()
    second = runtime.backend()
    await collect(second, call)
    process = runtime.processes[-1]
    assert ("thread/resume", {"threadId": "native-old"}) in process.requests
    await collect(second, runtime.call("bob"))
    saved = json.loads(
        (runtime.context.state_dir / "codex_sessions.json").read_text(),
    )
    assert saved[json.dumps(["alice", "console", "chat"])] == "native-old"
    assert saved[json.dumps(["bob", "console", "chat"])] != "native-old"
    assert [item.text for item in await second.history(call)] == [
        "Old prompt",
        "Old answer",
    ]
    await second.reset_session(call)
    assert await second.history(call) == ()
    await collect(second, call)
    assert dict(process.requests)["turn/start"]["threadId"] != "native-old"
    assert old.read_text() == '{"chat":"native-old"}'


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("approved", "accept"), ("rejected", "decline")],
)
async def test_approval_and_other_rpc_can_progress(runtime, outcome, expected):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def decide(summary, *, timeout):
        seen.append(
            (summary.tool_name, summary.parameters["command"], timeout),
        )
        entered.set()
        await release.wait()
        return outcome

    backend = runtime.backend()
    call = runtime.call(_request_approval=decide)
    task = asyncio.create_task(collect(backend, call, "approve"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (await asyncio.wait_for(backend.models(call), 2))[
            0
        ].id == "gpt-test"
        assert not task.done()
        release.set()
        assert (await task)[-1].kind == HarnessEventKind.COMPLETED
        assert runtime.processes[-1].decisions == [{"decision": expected}]
        assert seen == [("Codex command", "pytest", 300)]
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancel_then_continue_and_close_reaps_client(runtime):
    backend, call = runtime.backend(), runtime.call()
    ready = asyncio.Event()

    async def consume():
        async for event in backend.run_turn(call, HarnessRunRequest("wait")):
            if event.kind == HarnessEventKind.TEXT_DELTA:
                ready.set()

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(ready.wait(), 2)
        process = runtime.processes[-1]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        interrupted = dict(process.requests)["turn/interrupt"]
        assert interrupted == process.current
        events = await collect(backend, call)
        assert [
            e.text for e in events if e.kind == HarnessEventKind.TEXT_DELTA
        ] == [
            "Done",
        ]
        assert events[-1].kind == HarnessEventKind.COMPLETED
        await backend.close()
        assert process.returncode == 0 and process.exited.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_actual_zip_manifest_registration_and_host_call(
    runtime,
    tmp_path,
):
    plugin_id = "qwenpaw-harness-codex"
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
            ("codex", plugin_id, "available"),
        ]
        output = [
            item
            async for item in host.run_harness(
                "codex",
                HarnessRunRequest("Review"),
                workspace_id="test",
                session_id="zip-call",
            )
        ]
        assert output[-1].status == "completed"
        assert "Done" in str(output) and "1 passed" in str(output)
        assert any(
            m == "turn/start" for p in runtime.processes for m, _ in p.requests
        )
