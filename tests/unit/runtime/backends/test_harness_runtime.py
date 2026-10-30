# -*- coding: utf-8 -*-
"""Core Harness behavior through plugin ownership, workspaces and routes."""

# pylint: disable=protected-access

import asyncio
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.plugins.testing import PluginTestHost

SOURCE = """
import asyncio
from qwenpaw.plugins.harnesses import (
    HarnessApprovalSummary, HarnessCapabilities, HarnessEvent,
    HarnessEventKind as Kind, HarnessHistoryItem, HarnessHistoryKind,
    HarnessSpec, HarnessStatus,
)

class Backend:
    def __init__(self, context, settings):
        self.context, self.settings = context, settings
        self.calls = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.closed = False
        self.decisions = {}
        self.resets = self.history_calls = 0

    async def status(self, context):
        self.calls.append(context)
        return HarnessStatus(installed=True, authenticated=True)

    async def run_turn(self, context, request):
        self.calls.append(context)
        self.last_request = request
        self.entered.set()
        if request.prompt == "approval":
            self.decisions[context.user_id] = await context.request_approval(
                HarnessApprovalSummary(
                    "shell", "Confirm", parameters={"user_id": "forged"}
                ),
                timeout=5,
            )
        yield HarnessEvent(Kind.TEXT_DELTA, text="answer")
        if request.prompt == "hold":
            await self.release.wait()
        yield HarnessEvent(
            Kind.TOOL_STARTED, item_id="tool", tool_name="shell",
            data={"arguments": {"command": "echo test"}},
        )
        yield HarnessEvent(
            Kind.TOOL_COMPLETED, item_id="tool",
            tool_name="shell", text="done",
        )
        yield HarnessEvent(Kind.COMPLETED)

    async def history(self, context):
        self.history_calls += 1
        return (
            HarnessHistoryItem(HarnessHistoryKind.USER, text="old question"),
            HarnessHistoryItem(HarnessHistoryKind.MESSAGE, text="old answer"),
        )

    async def reset_session(self, context):
        self.resets += 1

    async def list_external_threads(self, context, *, limit, archived):
        if archived:
            return ()
        return ({"id": "native-thread", "title": "Imported"},)

    async def read_external_thread(self, context, thread_id):
        assert thread_id == "native-thread"
        return await self.history(context)

    async def external_skill_records(self, context):
        return ()

    async def external_mcp_records(self, context):
        return ()

    async def close(self):
        self.closed = True

class Plugin:
    def register(self, context):
        self.created = []
        def create(factory_context, settings):
            backend = Backend(factory_context, settings)
            self.created.append(backend)
            return backend
        context.register_harness(HarnessSpec(
            "codex", "Codex", create,
            HarnessCapabilities(external_history=True),
            instance_settings_keys=("binary",),
        ))

plugin = Plugin()
"""


def package(tmp_path, backend="codex"):
    root = tmp_path / ("source-" + backend)
    root.mkdir()
    (root / "main.py").write_text(
        SOURCE.replace('"codex"', repr(backend)),
        encoding="utf-8",
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "qwenpaw-harness-" + backend,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {
                    "version": "1.1.0",
                    "capabilities": ["harnesses", "storage", "resources"],
                },
                "meta": {"harnesses": [{"id": backend, "label": backend}]},
            },
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture(name="host")
async def make_host(tmp_path):
    async with PluginTestHost(tmp_path / "host") as test_host:
        assert (await test_host.install(package(tmp_path))).ok
        yield test_host


def plugin(host):
    return host._loader.get_loaded_plugin("qwenpaw-harness-codex").instance


def request(
    prompt="hello",
    *,
    user="alice",
    channel="console",
    session="same",
):
    from qwenpaw.schemas import AgentRequest

    return AgentRequest(
        session_id=session,
        user_id=user,
        channel=channel,
        request_id="trusted",
        input=[
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
    )


async def collect(runtime, prompt="hello", *, settings=None, **identity):
    return [
        item
        async for item in runtime.stream(
            "codex",
            request(prompt, **identity),
            settings,
        )
    ]


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


NATIVE_CHILD = r"""
import asyncio, builtins, json, re, shutil, sys
from pathlib import Path
from unittest.mock import patch
forbidden = (
    "openai_codex", "codex_cli_bin", "qoder_agent_sdk", "qwenpaw.harnesses"
)
imports, probes, processes = [], [], []
original_import, original_which = builtins.__import__, shutil.which

def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + ".") for root in forbidden):
        imports.append(name)
        raise AssertionError(name)
    return original_import(name, *args, **kwargs)

def guarded_which(command, *args, **kwargs):
    if Path(str(command)).name.lower() in {"codex", "qoder", "qodercli"}:
        probes.append(command)
        raise AssertionError("vendor CLI probe")
    return original_which(command, *args, **kwargs)

def no_vendor_process(event, args):
    # Native governance may probe the OS sandbox (for example bwrap on Linux).
    # Audit command-bearing launches, while allowing native worker processes.
    if event in {"subprocess.Popen", "os.posix_spawn", "os.exec"}:
        command = args[:2]
    elif event == "os.system":
        command = args[:1]
    else:
        return
    if re.search(
        r"(?i)(?<![a-z0-9_])(codex|qoder|qodercli|openai_codex|"
        r"codex_cli_bin|qoder_agent_sdk)(?![a-z0-9_])",
        str(command),
    ):
        processes.append(command)
        raise AssertionError("vendor process launch")

builtins.__import__, shutil.which = guarded_import, guarded_which
sys.addaudithook(no_vendor_process)
from agentscope.formatter import OpenAIChatFormatter
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from qwenpaw.app import _app as actual_app
from qwenpaw.plugins.testing import PluginTestHost

class Model(ChatModelBase):
    def __init__(self):
        super().__init__(
            credential=None, model="local",
            parameters=ChatModelBase.Parameters(),
            stream=False, context_size=32768,
        )
        self.formatter = OpenAIChatFormatter()
    async def __call__(self, *args, **kwargs):
        return ChatResponse(
            content=[{"type": "text", "text": "native-answer"}], is_last=True
        )

async def main():
    assert actual_app.app is not None
    with patch("qwenpaw.agents.model_factory.create_model_and_formatter",
               side_effect=lambda **kwargs: (Model(), OpenAIChatFormatter())):
        async with PluginTestHost(Path(sys.argv[1])) as host:
            assert host.list_harnesses() == ()
            events = [event async for event in host.stream_chat("hello")]
            assert events[-1].status == "completed"
            history = (
                Path(sys.argv[1])
                / "workspaces/test/sessions/console/test.json"
            )
            saved = json.loads(history.read_text())
            assert any(block.get("text") == "native-answer"
                       for message in saved["agent"]["state"]["context"]
                       for block in message["content"])
    assert not (imports or probes or processes)
    assert not any(name == root or name.startswith(root + ".")
                   for name in sys.modules for root in forbidden)
    print("native-ok")
asyncio.run(main())
"""


def test_native_app_chat_and_history_do_not_touch_vendors(tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "QWENPAW_WORKING_DIR": str(tmp_path / "native"),
        "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
    }
    result = subprocess.run(
        [sys.executable, "-c", NATIVE_CHILD, str(tmp_path / "native")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native-ok"


async def test_management_replaces_instances_and_preserves_user_data(
    host,
    tmp_path,
):
    from qwenpaw.app.agent_startup import AgentStartupStatus
    from qwenpaw.app.routers.agents import router
    from qwenpaw.plugins import ResourceError, StaleContextError

    manager = host._workspace_manager
    manager.schedule_agent_startup = (
        manager.note_agent_config_changed
    ) = lambda _id: None
    manager.reload_agent = AsyncMock(return_value=False)
    manager.is_agent_startup_in_progress = lambda _id: False
    manager.stop_agent = AsyncMock()
    manager.get_agent_startup_status = (
        lambda _id, *, enabled: AgentStartupStatus.RUNNING
    )
    host._http_app.include_router(router, prefix="/api")
    assert (await host.install(package(tmp_path, "qoder"))).ok
    catalog = await host.request("GET", "/api/harnesses")
    assert {row["id"] for row in catalog.json()["providers"]} == {
        "codex",
        "qoder",
    }
    assert plugin(host).created == []
    created = await host.request(
        "POST",
        "/api/agents",
        json={"id": "third", "name": "Third", "backend": "codex"},
    )
    assert created.status == 201, created.text
    updated = await host.request(
        "PUT",
        "/api/agents/third",
        json={"id": "third", "name": "Renamed", "backend": "codex"},
    )
    assert updated.status == 200 and updated.json()["name"] == "Renamed"
    assert (await host.harness_status("codex", workspace_id="third")).installed
    old = plugin(host).created[0]
    old_context = old.calls[0]
    assert (await host.set_enabled("qwenpaw-harness-codex", False)).ok
    assert old.closed
    assert (await host.harness_status("qoder", workspace_id="third")).installed
    assert (await host.set_enabled("qwenpaw-harness-codex", True)).ok
    assert (await host.harness_status("codex", workspace_id="third")).installed
    new = plugin(host).created[0]
    assert new is not old and new.context is not old.context
    for scope in (old.context.resources, old_context.resources):
        with pytest.raises((ResourceError, StaleContextError)):
            scope.defer(lambda: None)
    agent_file = host.root / "workspaces/third/agent.json"
    data_file = host.root / "plugin-data/qwenpaw-harness-codex/account.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text('{"account":"retained"}', encoding="utf-8")
    before = agent_file.read_bytes(), data_file.read_bytes()
    removed = await host.uninstall("qwenpaw-harness-codex")
    assert removed.clean and removed.quiescent
    assert (agent_file.read_bytes(), data_file.read_bytes()) == before
    listed = await host.request("GET", "/api/agents")
    saved = next(
        row for row in listed.json()["agents"] if row["id"] == "third"
    )
    assert saved["backend"] == "codex" and saved["backend_status"] == "missing"
    assert (await host.request("DELETE", "/api/agents/third")).status == 200


async def test_stream_attachments_history_restore_and_clear(host, tmp_path):
    from qwenpaw.app.chats.utils import agentscope_msg_to_message
    from agentscope.state import AgentState

    workspace = await host._workspace("one")
    runtime, session = workspace.backend_runtime, workspace.session
    image, document = tmp_path / "picture.png", tmp_path / "notes.txt"
    image.write_bytes(b"image")
    document.write_text("notes", encoding="utf-8")
    incoming = request()
    incoming.input[0].content.extend(
        [
            {"type": "image", "image_url": str(image)},
            {
                "type": "file",
                "file_url": str(document),
                "filename": "notes.txt",
            },
        ],
    )
    # Validate the actual wire attachment values before entering the bridge.
    incoming = type(incoming).model_validate(incoming.model_dump())
    events = [event async for event in runtime.stream("codex", incoming)]
    backend = plugin(host).created[0]
    assert events[-1].status == "completed"
    assert [message.type.value for message in events[-1].output] == [
        "message",
        "plugin_call",
        "plugin_call_output",
    ]
    assert [item.path for item in backend.last_request.attachments] == [
        image,
        document,
    ]
    saved = await session.get_session_state_dict("same", "alice", "console")
    restored = agentscope_msg_to_message(
        list(AgentState.model_validate(saved["agent"]["state"]).context),
    )
    assert [item.type for item in restored[0].content] == [
        "text",
        "image",
        "file",
    ]
    assert restored[-1].content[0].data["output"] == "done"
    await collect(runtime, user="bob")
    await collect(runtime, "/clear")
    assert backend.resets == 1
    assert (await session.get_session_state_dict("same", "alice", "console"))[
        "agent"
    ]["state"]["context"] == []
    assert (await session.get_session_state_dict("same", "bob", "console"))[
        "agent"
    ]["state"]["context"]
    await runtime.hydrate_session(
        "codex",
        session_id="same",
        user_id="alice",
        channel="console",
    )
    await runtime.hydrate_session(
        "codex",
        session_id="same",
        user_id="alice",
        channel="console",
    )
    assert backend.history_calls == 1
    assert "old answer" in str(
        await session.get_session_state_dict("same", "alice", "console"),
    )


@pytest.mark.parametrize("close_fails", [False, True])
async def test_iterator_cleanup_finalizes_response_and_history(
    host,
    monkeypatch,
    close_fails,
):
    from agentscope.state import AgentState
    from qwenpaw.app.chats.utils import agentscope_msg_to_message
    from qwenpaw.plugins.harnesses import HarnessEvent, HarnessEventKind

    workspace = await host._workspace("one")
    runtime = workspace.backend_runtime
    await host.harness_status("codex", workspace_id="one")
    backend = plugin(host).created[0]

    class Events:
        def __init__(self):
            self.events = iter(
                [
                    HarnessEvent(HarnessEventKind.TEXT_DELTA, text="full "),
                    HarnessEvent(HarnessEventKind.TEXT_DELTA, text="answer"),
                    HarnessEvent(HarnessEventKind.COMPLETED),
                ],
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration:
                raise StopAsyncIteration from None

    stream = Events()
    close = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    if close_fails:
        stream.aclose = close
    monkeypatch.setattr(backend, "run_turn", Mock(return_value=stream))
    append = AsyncMock(wraps=runtime._session_bridge.append_turn)
    monkeypatch.setattr(runtime._session_bridge, "append_turn", append)
    events = await collect(runtime)
    response = events[-1]
    assert response.status == ("failed" if close_fails else "completed")
    assert response.output[0].status == "completed"
    assert [item.text for item in response.output[0].content] == [
        "full answer",
    ]
    if close_fails:
        close.assert_awaited_once_with()
        assert response.error["code"] == "harness_error"
        assert "cleanup failed" in response.error["message"]
    append.assert_awaited_once()
    saved = await workspace.session.get_session_state_dict(
        "same",
        "alice",
        "console",
    )
    restored = agentscope_msg_to_message(
        list(AgentState.model_validate(saved["agent"]["state"]).context),
    )
    assert [(item.role, item.content[0].text) for item in restored] == [
        ("user", "hello"),
        ("assistant", "full answer"),
    ]


async def test_concurrent_model_settings_and_status_reuse_backend(host):
    runtime = (await host._workspace("one")).backend_runtime
    settings = [
        {
            "binary": "one",
            "model": str(index),
            "permissions": mode,
            "turn": {"args": [index]},
        }
        for index, mode in enumerate(("read-only", "full-access"))
    ]
    tasks = [
        asyncio.create_task(collect(runtime, "hold", settings=options))
        for options in settings
    ]
    try:
        await until(
            lambda: plugin(host).created
            and len(plugin(host).created[0].calls) == 2,
        )
        assert len(plugin(host).created) == 1
        backend = plugin(host).created[0]
        calls = {
            context.settings["model"]: context for context in backend.calls
        }
        assert [calls[str(index)].settings for index in range(2)] == settings
        assert backend.settings == {"binary": "one"}
        settings[0]["turn"]["args"].append("caller mutation")
        assert calls["0"].settings["turn"]["args"] == [0]
        calls["0"].settings["turn"]["args"].append("first only")
        assert calls["1"].settings["turn"]["args"] == [1]
        status = await host.request(
            "POST",
            "/api/harnesses/codex/status",
            headers={"X-Agent-Id": "one"},
            json={"settings": {"binary": "one"}},
        )
        assert status.status == 200 and status.json()["installed"]
        assert len(plugin(host).created) == 1
        assert not backend.closed and not any(task.done() for task in tasks)
        assert backend.calls[-1].runtime_capabilities is None
        backend.release.set()
        assert all(
            events[-1].status == "completed"
            for events in await asyncio.gather(*tasks)
        )
    finally:
        for backend in plugin(host).created:
            backend.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_approvals_and_capabilities_keep_identity(host):
    from qwenpaw.app.approvals import get_approval_service
    from qwenpaw.app.approvals.service import (
        ApprovalActor,
        ApprovalIdentityMismatchError,
    )
    from qwenpaw.app.driver_config_service import DriverConfigService
    from qwenpaw.drivers.contracts import DriverCard, DriverPolicy
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    for name in ("one", "two"):
        workspace = await host._workspace(name)
        skill = workspace.workspace_dir / "skills" / "console-only"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: console-only\ndescription: test\n---\n",
            encoding="utf-8",
        )
        skill_config = {"enabled": True, "channels": ["console"]}
        (workspace.workspace_dir / "skill.json").write_text(
            json.dumps({"skills": {"console-only": skill_config}}),
            encoding="utf-8",
        )
        await DriverConfigService(workspace).save_card(
            DriverCard(
                name="private",
                protocol="mcp",
                endpoint={
                    "transport": "stdio",
                    "command": "never-run",
                    "env": {"TOKEN": name + "-secret"},
                },
                config={"tools": ["read"]},
                policy=DriverPolicy(default_effect="deny"),
            ),
            reload_driver=False,
        )
    identities = [
        ("one", "alice", "console"),
        ("one", "bob", "mail"),
        ("two", "alice", "console"),
    ]
    settings = [
        {
            "binary": "one",
            "model": str(index),
            "permissions": mode,
            "turn": {"args": [index]},
            "_request_context": {"user_id": "forged", "session_id": "forged"},
        }
        for index, mode in enumerate(("read-only", "full-access", "read-only"))
    ]
    tasks = [
        asyncio.create_task(
            collect(
                host._workspaces[name].backend_runtime,
                "approval",
                user=user,
                channel=channel,
                settings=options,
            ),
        )
        for (name, user, channel), options in zip(identities, settings)
    ]
    service = get_approval_service()
    try:
        async with asyncio.timeout(5):
            while (
                len(pending := await service.list_pending_by_session("same"))
                != 3
            ):
                await asyncio.sleep(0.005)
        pending = {
            (row.agent_id, row.user_id, row.channel): row for row in pending
        }
        assert set(pending) == set(identities)
        backends = {
            backend.context.workspace_id: backend
            for backend in plugin(host).created
        }
        assert set(backends) == {"one", "two"}
        assert (
            backends["one"].context.state_dir
            != backends["two"].context.state_dir
        )
        calls = {
            context.settings["model"]: context
            for backend in backends.values()
            for context in backend.calls
        }
        for index, (_, user, channel) in enumerate(identities):
            context = calls[str(index)]
            assert (
                context.request_id,
                context.session_id,
                context.user_id,
                context.channel,
            ) == ("trusted", "same", user, channel)
            assert context.settings == settings[index]
            capabilities = context.runtime_capabilities
            expected_skills = ["console-only"] if channel == "console" else []
            assert [
                skill.name for skill in capabilities.skills
            ] == expected_skills
            server = capabilities.mcp_servers[0]
            assert server.revealed_env() == {
                "TOKEN": identities[index][0] + "-secret",
            }
            assert server.tool_policies == {"read": "deny"}
            assert "-secret" not in repr(capabilities)
        actors = {
            key: ApprovalActor("same", "same", key[1], key[2], key[0])
            for key in identities
        }
        with pytest.raises(ApprovalIdentityMismatchError):
            await service.resolve_request(
                pending[identities[0]].request_id,
                ApprovalDecision.APPROVED,
                actor=actors[identities[2]],
            )
        for key, row in pending.items():
            decision = (
                ApprovalDecision.DENIED
                if row.user_id == "bob"
                else ApprovalDecision.APPROVED
            )
            await service.resolve_request(
                row.request_id,
                decision,
                actor=actors[key],
            )
        assert all(
            events[-1].status == "completed"
            for events in await asyncio.gather(*tasks)
        )
        assert backends["one"].decisions == {
            "alice": "approved",
            "bob": "rejected",
        }
        assert backends["two"].decisions == {"alice": "approved"}
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("mode", ["sse", "task"])
@pytest.mark.parametrize("state", ["missing", "disabled", "busy"])
async def test_console_exposes_unavailable_and_busy_failures(
    host,
    monkeypatch,
    mode,
    state,
):
    from qwenpaw.app.channels.console.channel import ConsoleChannel
    from qwenpaw.app.routers import console
    from qwenpaw.runtime.runtime import Runtime

    workspace = await host._workspace("test")
    runtime = workspace.backend_runtime
    active = None
    if state == "busy":
        active = asyncio.create_task(
            collect(runtime, "hold", settings={"binary": "one"}),
        )
        await until(
            lambda: plugin(host).created
            and plugin(host).created[0].entered.is_set(),
        )
    elif state == "disabled":
        assert (await host.set_enabled("qwenpaw-harness-codex", False)).ok
    else:
        assert (await host.uninstall("qwenpaw-harness-codex")).clean
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config_async",
        AsyncMock(
            return_value=SimpleNamespace(
                backend="codex",
                backend_settings={"binary": "two"},
            ),
        ),
    )
    channel = ConsoleChannel(
        process=workspace.stream_query,
        enabled=True,
        bot_prefix="",
        workspace_dir=workspace.workspace_dir,
    )
    chat = await workspace.chat_manager.get_or_create_chat(
        "same",
        "alice",
        "console",
    )
    workspace._service_manager.services["channel_manager"] = SimpleNamespace(
        get_channel=AsyncMock(return_value=channel),
        stop_all=AsyncMock(),
    )
    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    native = Mock(side_effect=AssertionError("native fallback"))
    monkeypatch.setattr(Runtime, "run", native)
    host._http_app.include_router(console.router, prefix="/api")
    try:
        response = await host.request(
            "POST",
            "/api/console/chat" + ("/task" if mode == "task" else ""),
            json=request().model_dump(mode="json"),
        )
        assert response.status == 200, response.text
        if mode == "task":
            task_id = response.json()["task_id"]
            await asyncio.wait_for(console._bg_tasks[task_id].asyncio_task, 5)
            response = await host.request(
                "GET",
                f"/api/console/chat/task/{task_id}",
            )
            assert response.json()["status"] == "finished"
            result = response.json()["result"]
        else:
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            result = events[-1] if events else {}
        assert result.get("status") == "failed", result
        assert result["error"]["code"] == (
            "plugin_busy" if state == "busy" else "backend_unavailable"
        )
        native.assert_not_called()
        assert await workspace.task_tracker.get_status(chat.id) == "idle"
        if active:
            assert len(plugin(host).created) == 1 and not active.done()
    finally:
        if active:
            plugin(host).created[0].release.set()
            await active
        console._bg_tasks.clear()


async def test_cancel_releases_busy_owner_and_next_turn_runs(host):
    from qwenpaw.plugins import PluginBusyError

    runtime = (await host._workspace("one")).backend_runtime
    task = asyncio.create_task(collect(runtime, "hold"))
    try:
        await until(
            lambda: plugin(host).created
            and plugin(host).created[0].entered.is_set(),
        )
        with pytest.raises(PluginBusyError):
            await host._loader.unload_plugin("qwenpaw-harness-codex")
        assert not plugin(host).created[0].closed
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (await collect(runtime))[-1].status == "completed"
    removed = await host.uninstall("qwenpaw-harness-codex")
    assert removed.clean and removed.quiescent


async def test_config_io_keeps_single_worker_loop_responsive(
    host,
    monkeypatch,
):
    workspace = await host._workspace("one")
    entered, release = threading.Event(), threading.Event()

    def held_read(agent_id):
        assert agent_id == "one"
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(backend="codex", backend_settings={})

    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", held_read)
    task = asyncio.create_task(anext(workspace.stream_query(request())))
    try:
        await until(entered.is_set)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and plugin(host).created == []
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_pawport_requires_plugin_before_scan_then_reads_history(
    host,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.portability import providers
    from qwenpaw.portability.models import SourceLocation

    workspace = await host._workspace("destination")
    assert (await host.uninstall("qwenpaw-harness-codex")).clean
    scan = Mock(side_effect=AssertionError("source directory scanned"))
    with monkeypatch.context() as scoped:
        scoped.setattr(providers, "resolve_source_location", scan)
        with pytest.raises(providers.HarnessPluginRequiredError) as caught:
            providers.create_migration_provider("codex", workspace)
        assert caught.value.detail == {
            "code": "harness_plugin_required",
            "source": "codex",
            "plugin_id": "qwenpaw-harness-codex",
            "state": "missing",
        }
        scan.assert_not_called()
    assert (await host.install(tmp_path / "source-codex")).ok
    provider = providers.create_migration_provider(
        "codex",
        workspace,
        source_location=SourceLocation(
            provider_id="codex",
            data_home=str(tmp_path / "empty-codex-home"),
        ),
    )
    inventory = await provider.inventory(limit=3)
    assert len(inventory.sessions) == 1
    assert inventory.sessions[0].source_id == "native-thread"
    assert [item.text for item in inventory.sessions[0].history] == [
        "old question",
        "old answer",
    ]
