# -*- coding: utf-8 -*-
"""Backend routing on the actual native tool, with real local fallback probes."""

import asyncio
import shlex

import pytest

from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.plugins.shell import ShellBackendSpec, ShellResult
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.runtime.tool_guard import GuardedFunctionTool
from qwenpaw.governance.tool_adapter import PolicyGuardedTool

from .sdk_author_fixture import make_plugin


@pytest.mark.parametrize("policy", [False, True])
async def test_reload_does_not_deselect_remote_backend(tmp_path, policy):
    source = (
        "from qwenpaw.plugins.shell import ShellBackendSpec, ShellResult\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        self.selected = False\n"
        "        async def execute(call, request):\n"
        "            return ShellResult(0, 'REMOTE')\n"
        "        ctx.register_shell_backend(ShellBackendSpec(\n"
        "            'remote', lambda identity: self.selected, execute))\n"
        "plugin = Plugin()\n"
    )
    package = make_plugin(
        tmp_path,
        source,
        ["shell"],
        sdk_version="1.2.0",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(package)
        await host._workspace("test")
        record = host._loader.get_loaded_plugin("extension-contract")
        record.instance.selected = True
        native = tool(policy=policy)
        assert (await native(command="echo LOCAL")).content[0].text == "REMOTE"

        report = await host.reload("extension-contract")
        assert (report.ok, report.errors) == (True, ())
        for _ in range(2):
            result = await native(command="echo LOCAL")
            assert "local execution refused" in result.content[0].text
            assert "LOCAL" not in result.content[0].text

        record = host._loader.get_loaded_plugin("extension-contract")
        record.instance.selected = True
        assert (await native(command="echo LOCAL")).content[0].text == "REMOTE"
        record.instance.selected = False
        result = await native(command="echo LOCAL")
        assert result.content[0].text.strip() == "LOCAL"


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
        await host._workspace("test")
        marker = tmp_path / "MUST_NOT_RUN_LOCALLY"
        command = "touch " + shlex.quote(str(marker))
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
            result = await tool(**arguments)(command="printf LOCAL")
            assert "LOCAL" in result.content[0].text
        assert len(seen) == count
        selected.clear()  # A deliberate disconnect makes the matcher false.
        assert (
            "LOCAL" in (await tool()(command="printf LOCAL")).content[0].text
        )
        selected.add(("test", "selected", "alice"))
        await tool()(command="echo remote")
        await handles[0].close()
        unavailable = await tool()(command=command)
        assert (
            "unavailable" in unavailable.content[0].text
            and not marker.exists()
        )


async def test_cancel_timeout_and_ambiguous_selection(sdk_component):
    entered, ended = asyncio.Event(), asyncio.Event()
    holder = []

    def declare(ctx):
        async def execute(call, request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                ended.set()
            return ShellResult(0)

        holder.append(ctx)
        ctx.register_shell_backend(
            ShellBackendSpec("slow", lambda _: True, execute),
        )

    async with sdk_component(declare, capabilities=("shell",)) as (host, ctx):
        await host._workspace("test")
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

        async def extra(call, request):
            pytest.fail("Ambiguous backends must not execute")

        ctx.register_shell_backend(
            ShellBackendSpec("extra", lambda _: True, extra),
        )
        result = await tool()(command="unused")
        assert "Multiple shell backends" in result.content[0].text
