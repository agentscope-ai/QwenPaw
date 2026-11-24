# -*- coding: utf-8 -*-
"""Backend routing on the actual native tool, with real local fallback probes."""

import asyncio
import os
import shlex
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.agents.tools import shell as native_shell
from qwenpaw.app.channels.command_registry import CommandRegistry
from qwenpaw.app.chats.api import create_chat
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.plugins.shell import ShellBackendSpec, ShellResult
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.tool_guard import GuardedFunctionTool
from qwenpaw.governance.tool_adapter import PolicyGuardedTool
from qwenpaw.schemas import AgentRequest

from .sdk_author_fixture import make_plugin


@pytest.mark.parametrize(
    ("arguments", "configured", "expected"),
    [
        ({}, 120.0, 120.0),
        ({}, None, 60.0),
        ({"timeout": 60.0}, 120.0, 120.0),
        ({"timeout": 90.0}, 120.0, 90.0),
        ({"timeout": "90"}, 120.0, 90.0),
        ({"timeout": "invalid"}, 120.0, 120.0),
    ],
)
def test_shell_timeout_resolution(
    monkeypatch,
    arguments,
    configured,
    expected,
):
    monkeypatch.setattr(
        native_shell,
        "get_current_shell_command_timeout",
        lambda: configured,
    )
    assert native_shell.resolve_shell_command_timeout(**arguments) == expected


@pytest.mark.parametrize(
    ("policy", "arguments", "expected"),
    [(False, {}, 120.0), (True, {"timeout": 90.0}, 90.0)],
)
async def test_remote_and_local_share_effective_timeout(
    sdk_component,
    monkeypatch,
    policy,
    arguments,
    expected,
):
    seen = []

    async def execute(call, request):
        seen.append(request.timeout)
        return ShellResult(0, "REMOTE")

    def declare(ctx):
        ctx.register_shell_backend(
            ShellBackendSpec("remote", lambda _: True, execute),
        )

    monkeypatch.setattr(
        native_shell,
        "get_current_shell_command_timeout",
        lambda: 120.0,
    )
    local = AsyncMock(return_value=(0, "LOCAL", ""))
    monkeypatch.setattr(native_shell, "_execute_posix_host", local)
    monkeypatch.setattr(native_shell, "_execute_windows_host", local)
    async with sdk_component(declare, capabilities=("shell",)) as (host, _):
        workspace = await host._workspace("test")
        chats = workspace.chat_manager
        await chats.get_or_create_chat("selected", "alice", "console")
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            "resource-contract:remote",
        )
        native = tool(policy=policy)
        assert (await native(command="echo ok", **arguments)).content[
            0
        ].text == "REMOTE"
        assert seen == [expected]
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            None,
        )
        assert (await native(command="echo ok", **arguments)).content[
            0
        ].text == "LOCAL"
        assert local.call_args.args[2] == expected


async def test_reload_does_not_deselect_remote_backend(tmp_path):
    source = (
        "from qwenpaw.plugins.apps import PawApp\n"
        "from qwenpaw.plugins.commands import CommandSpec, CommandResult\n"
        "from qwenpaw.plugins.messages import Message, ContentBlock\n"
        "from qwenpaw.plugins.shell import ShellBackendSpec, ShellResult\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        self.selected = False\n"
        "        async def execute(call, request):\n"
        "            return ShellResult(0, 'REMOTE')\n"
        "        ctx.register_shell_backend(ShellBackendSpec(\n"
        "            'remote', lambda identity: self.selected, execute))\n"
        "        async def select(call, arguments):\n"
        "            await call.select_shell_backend(arguments or None)\n"
        "            return CommandResult('reply', Message(\n"
        "                'assistant', (ContentBlock(text='changed'),)))\n"
        "        ctx.register_command(CommandSpec('select-backend', select, control=True))\n"
        "        app = PawApp(app_id='shell-selection')\n"
        "        @app.route('/select', methods=('POST',))\n"
        "        async def choose(call, request):\n"
        "            await call.select_shell_backend('remote')\n"
        "            return {'selected': True}\n"
        "        ctx.register_app(app)\n"
        "plugin = Plugin()\n"
    )
    package = make_plugin(
        tmp_path,
        source,
        ["shell", "commands", "apps"],
        sdk_version="1.2.0",
    )

    def shell_tools():
        return (tool(), tool(policy=True))

    async def outputs(shells):
        return [
            (await shell(command="echo LOCAL")).content[0].text
            for shell in shells
        ]

    async def assert_runs_locally(shells):
        assert [output.strip() for output in await outputs(shells)] == [
            "LOCAL",
            "LOCAL",
        ]

    async def assert_refuses_local(shells):
        for output in await outputs(shells):
            assert "local execution refused" in output
            assert "LOCAL" not in output

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(package)
        workspace = await host._workspace("test")
        chat = await workspace.chat_manager.get_or_create_chat(
            "selected",
            "alice",
            "console",
        )
        record = host._loader.get_loaded_plugin("extension-contract")
        record.instance.selected = True
        native = shell_tools()
        for user, expected in (("bob", 403), ("alice", 200)):
            response = await host.request(
                "POST",
                "/api/shell-selection/select?agent_id=test",
                headers={"X-Chat-Id": chat.id},
                user_id=user,
            )
            assert response.status == expected, response.text

        report = await host.reload("extension-contract")
        assert (report.ok, report.errors) == (True, ())
        for _ in range(2):
            await assert_refuses_local(native)
        runtime = await host._request_context(
            "test",
            "selected",
            user_id="alice",
        )
        runtime.request = AgentRequest(
            session_id="selected",
            user_id="alice",
            channel="console",
            request_context={"session_id": "other", "user_id": "bob"},
        )
        await assert_refuses_local(
            cls(
                execute_shell_command,
                request_context=AgentBuilder._build_request_context(runtime),
            )
            for cls in (GuardedFunctionTool, PolicyGuardedTool)
        )
        assert (await tool(user="bob")(command="echo LOCAL")).content[
            0
        ].text.strip() == "LOCAL"

        record = host._loader.get_loaded_plugin("extension-contract")
        record.instance.selected = True
        assert await outputs(native) == ["REMOTE", "REMOTE"]
        reply = await host.call_control_command(
            "/select-backend",
            user_id="alice",
            session_id="selected",
        )
        assert reply.content[0].text == "changed"
        await assert_runs_locally(native)
        await host.call_control_command(
            "/select-backend remote",
            user_id="alice",
            session_id="selected",
        )
        report = await host.unload("extension-contract")
        assert report.clean and report.quiescent
        await assert_refuses_local(native)
        assert CommandRegistry().is_control_command("/shell-local")
        reply = await host.call_command(
            "/shell-local",
            user_id="alice",
            session_id="selected",
        )
        assert "now uses the local shell" in reply.content[0].text
        await assert_runs_locally(native)
        await host.load(package)
        await host.call_control_command(
            "/select-backend remote",
            user_id="alice",
            session_id="selected",
        )

    async with PluginTestHost(tmp_path / "host") as restarted:
        await restarted._workspace("test")
        await assert_refuses_local(shell_tools())

    async with PluginTestHost(
        tmp_path / "host",
        workspace_dirs={"test": "new-workspace"},
    ) as recreated:
        workspace = await recreated._workspace("test")
        await workspace.chat_manager.get_or_create_chat(
            "selected",
            "alice",
            "console",
        )
        await assert_runs_locally(shell_tools())


def tool(user="alice", session="selected", workspace="test", policy=False):
    cls = PolicyGuardedTool if policy else GuardedFunctionTool
    return cls(
        execute_shell_command,
        request_context={
            "agent_id": workspace,
            "session_id": session,
            "user_id": user,
            "channel": "console",
        },
    )


async def test_selected_backend_failure_never_runs_locally(
    sdk_component,
    tmp_path,
):
    selected, seen, handles = {("test", "selected", "alice")}, [], []

    def declare(ctx):
        def matches(identity):
            return (
                identity.workspace_id,
                identity.session_id,
                identity.user_id,
            ) in selected

        async def execute(call, request):
            seen.append((call.identity, request))
            if request.cwd == "fail":
                raise ConnectionError("connection was lost")
            return ShellResult(0, "remote:" + str(request.cwd))

        handles.append(
            ctx.register_shell_backend(
                ShellBackendSpec("remote", matches, execute),
            ),
        )

    async with sdk_component(declare, capabilities=("shell",)) as (host, _):
        workspace = await host._workspace("test")
        chats = workspace.chat_manager
        await chats.get_or_create_chat("selected", "alice", "console")
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            "resource-contract:remote",
        )
        marker = tmp_path / "MUST_NOT_RUN_LOCALLY"
        command = (
            f'type NUL > "{marker}"'
            if os.name == "nt"
            else "touch " + shlex.quote(str(marker))
        )
        await tool(session="unselected")(command=command)
        assert marker.is_file()
        marker.unlink()
        for policy in (False, True):
            result = await tool(policy=policy)(
                command=command,
                cwd="/remote/only",
                timeout=3,
            )
            assert result.content[0].text == "remote:/remote/only"
            assert seen[-1][0].user_id == "alice"
            assert seen[-1][1].command == command and seen[-1][1].timeout == 3
            failed = await tool(policy=policy)(command=command, cwd="fail")
            assert "local execution refused" in failed.content[0].text
            assert not marker.exists()
            blocked = await tool(policy=policy)(
                command=command,
                sandbox_config=object(),
            )
            assert "required local sandbox policy" in blocked.content[0].text
            assert not marker.exists()
        count = len(seen)
        for arguments in (
            {"user": "bob"},
            {"session": "other"},
            {"workspace": "two"},
        ):
            result = await tool(**arguments)(command="echo LOCAL")
            assert result.content[0].text.strip() == "LOCAL"
        assert len(seen) == count
        selected.clear()
        assert (
            "local execution refused"
            in (await tool()(command=command)).content[0].text
        )
        assert not marker.exists()
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            None,
        )
        result = await tool()(command="echo LOCAL")
        assert result.content[0].text.strip() == "LOCAL"
        selected.add(("test", "selected", "alice"))
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            "resource-contract:remote",
        )
        await tool()(command="echo remote")
        await handles[0].close()
        unavailable = await tool()(command=command)
        assert (
            "unavailable" in unavailable.content[0].text
            and not marker.exists()
        )


async def test_shell_target_is_independent_of_chat_metadata_and_catalog(
    sdk_component,
    monkeypatch,
):
    async def execute(call, request):
        return ShellResult(0, "REMOTE")

    def declare(ctx):
        ctx.register_shell_backend(
            ShellBackendSpec("remote", lambda identity: True, execute),
        )

    key = "resource-contract:remote"
    async with sdk_component(declare, capabilities=("shell",)) as (host, _):
        workspace = await host._workspace("test")
        chats = workspace.chat_manager
        identity = ("selected", "alice", "console")
        chat = await create_chat(
            ChatSpec(
                session_id=identity[0],
                user_id=identity[1],
                channel=identity[2],
                meta={"shell_backend": key},
            ),
            mgr=chats,
        )
        laptop = tool()
        with monkeypatch.context() as patch:
            load = AsyncMock(side_effect=AssertionError("Opened chat catalog"))
            patch.setattr(chats._repo, "load", load)
            result = await laptop(command="echo LOCAL")
            assert result.content[0].text.strip() == "LOCAL"
            load.assert_not_awaited()

        assert await chats.set_shell_backend(*identity, key)
        assert not await chats.set_shell_backend(
            *identity,
            None,
            owner="other",
        )
        with monkeypatch.context() as patch:
            load = AsyncMock(side_effect=AssertionError("Opened chat catalog"))
            patch.setattr(chats._repo, "load", load)
            assert (await laptop(command="echo LOCAL")).content[0].text == (
                "REMOTE"
            )
            load.assert_not_awaited()

        assert await chats.delete_chats([chat.id])
        assert await chats.shell_backend_for(*identity) is None


async def test_selected_shell_cancellation_and_timeout(sdk_component):
    entered, ended = asyncio.Event(), asyncio.Event()

    def declare(ctx):
        async def execute(call, request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                ended.set()
            return ShellResult(0)

        ctx.register_shell_backend(
            ShellBackendSpec("slow", lambda _: True, execute),
        )

    async with sdk_component(declare, capabilities=("shell",)) as (host, _):
        workspace = await host._workspace("test")
        chats = workspace.chat_manager
        await chats.get_or_create_chat("selected", "alice", "console")
        assert await chats.set_shell_backend(
            "selected",
            "alice",
            "console",
            "resource-contract:slow",
        )
        running = asyncio.create_task(tool()(command="unused", timeout=30))
        await asyncio.wait_for(entered.wait(), 5)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert ended.is_set()
        ended.clear()
        result = await tool()(command="unused", timeout=0.02)
        assert (
            "local execution refused" in result.content[0].text
            and ended.is_set()
        )
